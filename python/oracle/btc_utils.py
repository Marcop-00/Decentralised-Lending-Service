"""
btc_utils.py — Utilities for parsing Bitcoin mainnet blk.dat files.

blk.dat file format
────────────────────
Each file is a sequence of records in this layout:

    [magic: 4 bytes = F9 BE B4 D9]  ← identifies Bitcoin mainnet
    [size:  4 bytes, uint32 LE   ]  ← block size in bytes
    [block: size bytes           ]  ← serialised block (header + transactions)

Files are named blk00000.dat, blk00001.dat, etc.

Block ordering inside blk*.dat
──────────────────────────────
Bitcoin Core writes blocks to disk in the order it RECEIVES them from the
network, NOT in chain order. Headers-first sync (since v0.10) plus parallel
block download means the physical layout in blk*.dat does NOT match the
canonical chain order. Empirically, on the first 5000 blocks of the bundled
files, ~40 % of the records are out-of-order relative to their parents.

Iterating the file linearly therefore produces an UTXO set that is silently
corrupted: a transaction may spend an UTXO whose creating block has not been
seen yet, and the spend is dropped on the floor. The Project spec (§1.4)
requires the oracle to elaborate blocks "as if generated as normal", which
means in canonical-chain order.

For this reason `parse_blocks()` runs a two-pass algorithm:
  • Pass 1: scan all blk*.dat files reading only the 80-byte header per
    record. Build (a) hash → (file, offset, prev_hash, work) and
    (b) prev_hash → [child_hash, …]. Memory cost ≈ 100 bytes / block.
  • Pass 2: walk the graph from genesis (the block whose prev_hash is
    0x00…00). On forks, pick the branch with greater cumulative work
    (Bitcoin's canonical-chain rule). Yield blocks in chain order,
    re-reading them from disk by seek(offset).

The result is a generator that emits (height, CBlock) pairs in canonical
order, where `height` is the TRUE block height (0 = genesis).
"""

import hashlib
import logging
import os
import struct
from collections import defaultdict
from collections.abc import Generator

import bitcoin
from bitcoin.core import CBlock, b2lx

# Sets mainnet magic bytes, address prefixes, etc.
bitcoin.SelectParams("mainnet")

logger = logging.getLogger(__name__)

# Bitcoin mainnet magic (little-endian in blk.dat)
MAINNET_MAGIC = bytes.fromhex("F9BEB4D9")

# Sentinel hashPrevBlock value for the genesis block.
GENESIS_PREV = b"\x00" * 32
MAINNET_GENESIS_HASH = bytes.fromhex(
    "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
)[::-1]


class BlockDataError(ValueError):
    """The source cannot provide a complete, consistent mainnet snapshot."""


# ─── File iteration ───────────────────────────────────────────────────────────

def _iter_blk_files(blk_dir: str) -> Generator[str, None, None]:
    """Yield blk.dat file paths in ascending numeric order, stopping at the first gap."""
    index = 0
    while True:
        path = os.path.join(blk_dir, f"blk{index:05d}.dat")
        if not os.path.exists(path):
            break
        yield path
        index += 1


def _resolve_files(blk_dat_path: str) -> list[str]:
    """Accept either a directory of blk*.dat files or a single .dat file."""
    if os.path.isdir(blk_dat_path):
        return list(_iter_blk_files(blk_dat_path))
    return [blk_dat_path] if os.path.exists(blk_dat_path) else []


# ─── Work calculation ─────────────────────────────────────────────────────────

def _work_from_bits(bits: int) -> int:
    """
    Compute the proof-of-work value contributed by a block whose header
    encodes the target difficulty as `bits` (compact representation).

    Bitcoin's canonical-chain rule selects, on a fork, the branch with the
    greater SUM of per-block work, where per-block work is

        work = 2**256 // (target + 1)

    The compact `bits` field encodes the target as
        target = mantissa * 256**(exponent - 3)

    with `exponent` in the high byte and a 24-bit mantissa in the low bytes.
    """
    exponent = (bits >> 24) & 0xFF
    mantissa = bits & 0x007FFFFF
    if exponent <= 3:
        target = mantissa >> (8 * (3 - exponent))
    else:
        target = mantissa << (8 * (exponent - 3))
    if target <= 0:
        return 0
    return (1 << 256) // (target + 1)


def _hash_block_header(header: bytes) -> bytes:
    """Bitcoin block hash = SHA256(SHA256(header)). Returns the 32-byte digest
    in little-endian (internal) representation — same as `hashPrevBlock`."""
    return hashlib.sha256(hashlib.sha256(header).digest()).digest()


# ─── Pass 1: header scan ──────────────────────────────────────────────────────

class _HeaderRecord:
    __slots__ = ("file_path", "hash", "offset", "prev", "size", "work")

    def __init__(self, hash_: bytes, prev: bytes, work: int,
                 file_path: str, offset: int, size: int) -> None:
        self.hash = hash_
        self.prev = prev
        self.work = work
        self.file_path = file_path
        self.offset = offset
        self.size = size


def _scan_headers(files: list[str]) -> list[_HeaderRecord]:
    """
    Walk every blk*.dat file, read only the 80-byte header of each record,
    skip the rest of the block, and accumulate one _HeaderRecord per block.

    Memory cost: ~100 bytes per block. For 131 000 blocks this is ~13 MB.
    """
    records: list[_HeaderRecord] = []
    total_bytes = 0

    for file_path in files:
        logger.info("  Scanning headers: %s", os.path.basename(file_path))
        with open(file_path, "rb") as f:
            while True:
                magic = f.read(4)
                if not magic:
                    break
                if magic == b"\x00\x00\x00\x00":
                    # Bitcoin Core may preallocate a zero-filled tail. A mixed
                    # tail is corruption, not a reason to silently stop syncing.
                    if any(f.read()):
                        raise BlockDataError(f"Nonzero data after padding in {file_path}")
                    break
                if len(magic) < 4:
                    raise BlockDataError(f"Truncated magic in {file_path} at offset {f.tell() - len(magic)}")
                if magic != MAINNET_MAGIC:
                    raise BlockDataError(
                        f"Unexpected magic in {file_path} at offset {f.tell() - 4}: {magic.hex()}"
                    )

                size_bytes = f.read(4)
                if len(size_bytes) < 4:
                    raise BlockDataError(f"Truncated block size in {file_path} at offset {f.tell()}")
                block_size = struct.unpack("<I", size_bytes)[0]
                if block_size < 81 or block_size > 4_000_000:
                    raise BlockDataError(f"Invalid block size {block_size} in {file_path} at offset {f.tell() - 4}")

                # Offset where the block payload begins (= start of header)
                block_offset = f.tell()
                if block_offset + block_size > os.fstat(f.fileno()).st_size:
                    raise BlockDataError(f"Truncated block payload in {file_path} at offset {block_offset}")

                header = f.read(80)
                if len(header) < 80:
                    raise BlockDataError(f"Truncated block header in {file_path} at offset {block_offset}")

                hash_prev = header[4:36]                     # bytes 4..36
                bits = struct.unpack("<I", header[72:76])[0]  # bytes 72..76
                block_hash = _hash_block_header(header)
                work = _work_from_bits(bits)

                records.append(_HeaderRecord(
                    hash_=block_hash,
                    prev=hash_prev,
                    work=work,
                    file_path=file_path,
                    offset=block_offset,
                    size=block_size,
                ))

                total_bytes += block_size + 8  # block + magic + size

                # Skip the rest of the block payload
                remaining = block_size - 80
                if remaining > 0:
                    f.seek(remaining, 1)

    logger.info(
        "  Header scan complete: %d block headers, ~%.1f MB of payload",
        len(records), total_bytes / (1024 * 1024),
    )
    return records


# ─── Pass 2: canonical chain selection ────────────────────────────────────────

def _build_canonical_chain(records: list[_HeaderRecord]) -> list[_HeaderRecord]:
    """
    Build the canonical chain (greatest cumulative work) starting from
    genesis. Returns the list of records in chain order, from height 0
    upwards. Stops at the first orphan gap.

    Algorithm:
      1. Index records by hash, and by prev_hash → children.
      2. Anchor the chain to the known Bitcoin mainnet genesis hash.
      3. Iterative BFS/DFS from genesis, computing cumulative work for
         each reachable block. Track the heaviest tip.
      4. Reconstruct the chain from the heaviest tip back to genesis via
         the parent map, then reverse to get ascending-height order.
    """
    by_hash: dict[bytes, _HeaderRecord] = {r.hash: r for r in records}
    children: dict[bytes, list[bytes]] = defaultdict(list)
    for r in records:
        children[r.prev].append(r.hash)

    # ── locate genesis ────────────────────────────────────────────────────────
    genesis = by_hash.get(MAINNET_GENESIS_HASH)
    if genesis is None or genesis.prev != GENESIS_PREV:
        raise BlockDataError("The Bitcoin mainnet genesis block is missing or invalid")
    genesis_candidates = [MAINNET_GENESIS_HASH]

    # ── BFS computing cumulative work + parent map ────────────────────────────
    cum_work: dict[bytes, int] = {}
    parent: dict[bytes, bytes | None] = {}

    best_tip: bytes | None = None
    best_work = -1

    # Iterative DFS using an explicit stack — avoids Python recursion limits
    # on chains tens of thousands of blocks long.
    stack: list[bytes] = []
    for g in genesis_candidates:
        cum_work[g] = by_hash[g].work
        parent[g] = None
        stack.append(g)

    while stack:
        h = stack.pop()
        w = cum_work[h]
        if w > best_work:
            best_work = w
            best_tip = h
        for c in children.get(h, []):
            if c in cum_work:
                # Should not happen in a well-formed DAG of headers,
                # but if it does we keep the heavier path.
                if cum_work[h] + by_hash[c].work > cum_work[c]:
                    cum_work[c] = cum_work[h] + by_hash[c].work
                    parent[c] = h
                    stack.append(c)
                continue
            cum_work[c] = w + by_hash[c].work
            parent[c] = h
            stack.append(c)

    if best_tip is None:
        return []

    # ── reconstruct chain genesis → best_tip ──────────────────────────────────
    chain_hashes: list[bytes] = []
    h: bytes | None = best_tip
    while h is not None:
        chain_hashes.append(h)
        h = parent[h]
    chain_hashes.reverse()

    return [by_hash[h] for h in chain_hashes]


# ─── Pass 3: yield blocks in canonical order ──────────────────────────────────

def parse_blocks(
    blk_dat_path: str,
    max_blocks: int = 131_000,
) -> Generator[tuple[int, CBlock], None, None]:
    """
    Yield (height, CBlock) pairs in canonical-chain order.

    `height` is the TRUE block height (0 = genesis) — not the physical
    file position. Exactly `max_blocks` blocks must be available; missing
    or corrupt source data raises BlockDataError instead of a partial result.

    `blk_dat_path` may be a directory of blk*.dat files or a single .dat
    file. The single-file form is used by test_btc_utils.py to verify the
    genesis block in isolation.
    """
    if max_blocks <= 0:
        raise ValueError("max_blocks must be positive")
    files = _resolve_files(blk_dat_path)
    if not files:
        raise BlockDataError(f"No blk.dat files found in {blk_dat_path}")

    # Pass 1: read all headers (~13 MB RAM for 131k blocks)
    logger.info("Pass 1/2: scanning headers of %d file(s)…", len(files))
    records = _scan_headers(files)
    if not records:
        raise BlockDataError(f"No Bitcoin block records found in {blk_dat_path}")

    # Pass 2: build canonical chain by cumulative work
    logger.info("Pass 2/2: selecting canonical chain (cumulative work)…")
    canonical = _build_canonical_chain(records)
    if len(canonical) < max_blocks:
        raise BlockDataError(
            f"Incomplete Bitcoin mainnet chain: found {len(canonical)} connected blocks; "
            f"need {max_blocks} (heights 0..{max_blocks - 1})"
        )

    logger.info(
        "Canonical chain length: %d blocks (will yield first %d).",
        len(canonical), min(len(canonical), max_blocks),
    )

    # Pass 3: re-read each block in chain order via seek(offset)
    # Keep file handles open across iterations to amortise the open() cost.
    open_files: dict[str, object] = {}
    try:
        for height, rec in enumerate(canonical):
            if height >= max_blocks:
                break

            f = open_files.get(rec.file_path)
            if f is None:
                f = open(rec.file_path, "rb")
                open_files[rec.file_path] = f

            f.seek(rec.offset)
            raw = f.read(rec.size)
            if len(raw) < rec.size:
                raise BlockDataError(
                    f"Truncated block at height {height}: {len(raw)}/{rec.size} bytes"
                )

            try:
                block = CBlock.deserialize(raw)
            except Exception as exc:
                raise BlockDataError(
                    f"Cannot deserialize block at height {height} ({b2lx(rec.hash)}): {exc}"
                ) from exc
            if block.GetHash() != rec.hash or block.calc_merkle_root() != block.hashMerkleRoot:
                raise BlockDataError(f"Block integrity check failed at height {height}")

            yield height, block
    finally:
        for f in open_files.values():
            try:
                f.close()
            except Exception:
                pass


# ─── Coinbase + address helpers (unchanged) ───────────────────────────────────

def is_coinbase(tx) -> bool:
    """True if this is a coinbase transaction (first tx of every block).

    Coinbase inputs have prevout.hash = 0x00...00 and prevout.n = 0xFFFFFFFF.
    Coinbase inputs must never be looked up in the UTXO set.
    """
    return (
        len(tx.vin) == 1
        and tx.vin[0].prevout.hash == b"\x00" * 32
        and tx.vin[0].prevout.n == 0xFFFF_FFFF
    )


def script_to_address(script_pubkey) -> str | None:
    """Extract a human-readable Bitcoin address from a scriptPubKey.

    Recognised script types (matched against raw bytes for robustness across
    python-bitcoinlib versions — older builds lacked `CScript.is_p2pkh()`):

    1. P2PKH (25 bytes): OP_DUP OP_HASH160 <20> OP_EQUALVERIFY OP_CHECKSIG
       Encoded as 76 a9 14 <20 bytes> 88 ac.
    2. P2SH  (23 bytes): OP_HASH160 <20> OP_EQUAL
       Encoded as a9 14 <20 bytes> 87.
    3. P2PK  (35 or 67 bytes): <push33|65> <pubkey> OP_CHECKSIG
       The address is derived as the P2PKH of HASH160(pubkey) — this is the
       only script type used by the genesis block and most of the first
       ~25k mainnet blocks.

    Returns None for non-standard scripts (OP_RETURN, bare multisig, etc.).
    """
    from bitcoin.wallet import CBitcoinAddress

    raw = bytes(script_pubkey)

    # ── P2PKH: 76 a9 14 <20> 88 ac ────────────────────────────────────────────
    if (len(raw) == 25
            and raw[0] == 0x76        # OP_DUP
            and raw[1] == 0xA9        # OP_HASH160
            and raw[2] == 0x14        # push 20 bytes
            and raw[23] == 0x88       # OP_EQUALVERIFY
            and raw[24] == 0xAC):     # OP_CHECKSIG
        try:
            return str(CBitcoinAddress.from_scriptPubKey(script_pubkey))
        except Exception:
            return None

    # ── P2SH: a9 14 <20> 87 ──────────────────────────────────────────────────
    if (len(raw) == 23
            and raw[0] == 0xA9        # OP_HASH160
            and raw[1] == 0x14        # push 20 bytes
            and raw[22] == 0x87):     # OP_EQUAL
        try:
            return str(CBitcoinAddress.from_scriptPubKey(script_pubkey))
        except Exception:
            return None

    # ── P2PK uncompressed: 41 <65> ac ────────────────────────────────────────
    if len(raw) == 67 and raw[0] == 0x41 and raw[-1] == 0xAC:
        pubkey = raw[1:66]
        return _p2pk_to_address(pubkey)

    # ── P2PK compressed: 21 <33> ac ──────────────────────────────────────────
    if len(raw) == 35 and raw[0] == 0x21 and raw[-1] == 0xAC:
        pubkey = raw[1:34]
        return _p2pk_to_address(pubkey)

    return None


def _p2pk_to_address(pubkey: bytes) -> str | None:
    """Derive the P2PKH-equivalent address from a P2PK public key.

    This is an indexing convention for historical P2PK outputs; it does
    not change their locking script into P2PKH. The genesis coinbase is
    separately excluded from the UTXO set because it is unspendable.
    """
    from bitcoin.core.script import (
        OP_CHECKSIG,
        OP_DUP,
        OP_EQUALVERIFY,
        OP_HASH160,
        CScript,
    )
    from bitcoin.wallet import CBitcoinAddress

    try:
        pubkey_hash = _hash160(pubkey)
        p2pkh_script = CScript([
            OP_DUP, OP_HASH160, pubkey_hash, OP_EQUALVERIFY, OP_CHECKSIG,
        ])
        return str(CBitcoinAddress.from_scriptPubKey(p2pkh_script))
    except Exception:
        return None


def _hash160(data: bytes) -> bytes:
    """RIPEMD160(SHA256(data)) — standard Bitcoin hash for keys and scripts."""
    return hashlib.new("ripemd160", hashlib.sha256(data).digest()).digest()
