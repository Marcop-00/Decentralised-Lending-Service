"""Replay the required Bitcoin blocks, then serve balance-update requests.

UTXOs are rebuilt in memory at every start, one block at a time. The shared
event queue stores Ethereum requests and transactions, not Bitcoin balances.
"""

import logging
import os
from pathlib import Path
import sys
import time
from collections import defaultdict

from btc_utils import (
    BlockDataError, MAINNET_GENESIS_HASH, is_coinbase, parse_blocks, script_to_address,
)
from dotenv import load_dotenv
from web3 import Web3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from durable_events import (
    EventStore, make_web3, process_pending, require_local_chain, scan_events,
    send_durable, store_identity,
)

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────
MAX_BLOCKS    = 131_000
POLL_INTERVAL = 5

ORACLE_ABI = [
    {
        "name": "UpdateRequested",
        "type": "event",
        "anonymous": False,
        "inputs": [
            {"name": "btcAddress", "type": "string", "indexed": False},
            {"name": "requester",  "type": "address", "indexed": True},
            {"name": "fee",        "type": "uint256", "indexed": False},
        ],
    },
    {
        "name": "update",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "btcAddress",       "type": "string"},
            {"name": "balanceInSatoshi", "type": "uint256"},
        ],
        "outputs": [],
    }
]

utxo_set: dict[tuple[str, int], tuple[str, int]] = {}
addr_utxos: dict[str, dict[tuple[str, int], int]] = defaultdict(dict)

# ─── UTXO helpers ────────────────────────────────────────────────────────────
def _add_utxo(txid: str, vout: int, address: str, satoshi: int) -> None:
    # Historical duplicate transaction IDs replace the old outpoint. Keep
    # both indexes consistent even if an existing association changes.
    _remove_utxo(txid, vout)
    utxo_set[(txid, vout)] = (address, satoshi)
    addr_utxos[address][(txid, vout)] = satoshi

def _remove_utxo(txid: str, vout: int) -> None:
    entry = utxo_set.pop((txid, vout), None)
    if entry is not None:
        address, _ = entry
        addr_utxos[address].pop((txid, vout), None)
        if not addr_utxos[address]:
            del addr_utxos[address]

def process_block(block, block_height: int) -> None:
    """Apply one block atomically to the address index.

    Genesis counts towards the 131,000-block snapshot, but Bitcoin never
    inserts its coinbase into its UTXO set. Decode all other changes before
    committing so malformed data cannot leave half a block applied.
    """
    from bitcoin.core import b2lx
    if block_height < 0:
        raise BlockDataError("Block height must be nonnegative")
    if block_height == 0:
        if block.GetHash() != MAINNET_GENESIS_HASH:
            raise BlockDataError("Height zero is not the Bitcoin mainnet genesis block")
        return

    changes = []
    for tx in block.vtx:
        txid = b2lx(tx.GetTxid())
        if not is_coinbase(tx):
            for vin in tx.vin:
                spent_txid = b2lx(vin.prevout.hash)
                spent_vout = vin.prevout.n
                changes.append(((spent_txid, spent_vout), None))

        for i, vout in enumerate(tx.vout):
            address = script_to_address(vout.scriptPubKey)
            if address is None:
                continue
            if vout.nValue < 0:
                raise BlockDataError(f"Negative output value at height {block_height}")
            changes.append(((txid, i), (address, vout.nValue)))

    previous = {outpoint: utxo_set.get(outpoint) for outpoint, _ in changes}
    try:
        for outpoint, entry in changes:
            if entry is None:
                _remove_utxo(*outpoint)
            else:
                _add_utxo(*outpoint, *entry)
    except Exception:
        # Only touched outpoints need an undo record; copying the complete
        # UTXO set for every new block would make synchronization quadratic.
        for outpoint, entry in previous.items():
            _remove_utxo(*outpoint)
            if entry is not None:
                _add_utxo(*outpoint, *entry)
        raise

def get_address_balance(btc_address: str) -> int:
    return sum(addr_utxos.get(btc_address, {}).values())

# ─── Phase 1: Bitcoin blockchain sync ────────────────────────────────────────
def sync_bitcoin_blocks(blk_dat_dir: str) -> None:
    logger.info("=== SYNC Bitcoin: reading first %d blocks ===", MAX_BLOCKS)
    utxo_set.clear()
    addr_utxos.clear()
    blocks_processed = 0
    try:
        for block_height, block in parse_blocks(blk_dat_dir, max_blocks=MAX_BLOCKS):
            if block_height != blocks_processed or blocks_processed >= MAX_BLOCKS:
                raise BlockDataError(f"Unexpected Bitcoin block height {block_height}; expected {blocks_processed}")
            process_block(block, block_height)
            blocks_processed += 1
            if blocks_processed % 10_000 == 0:
                logger.info("  Processed %6d blocks | UTXO set: %d entries", blocks_processed, len(utxo_set))
        if blocks_processed != MAX_BLOCKS:
            raise BlockDataError(
                f"Incomplete Bitcoin snapshot: processed {blocks_processed}/{MAX_BLOCKS} blocks"
            )
    except Exception as exc:
        utxo_set.clear()
        addr_utxos.clear()
        raise BlockDataError(
            f"Bitcoin sync failed after {blocks_processed} blocks; no balances will be published: {exc}"
        ) from exc
    logger.info("SYNC complete: %d blocks processed", blocks_processed)

# ─── Phase 2: Ethereum event polling ─────────────────────────────────────────
def send_update(oracle_contract, operator_account, w3, btc_address, balance, store, event_id):
    receipt = send_durable(
        w3, operator_account, oracle_contract.functions.update(btc_address, balance), store, event_id,
    )
    logger.info("update(%s, %s satoshi) confirmed in block %s", btc_address, balance, receipt["blockNumber"])


def run_polling_loop(oracle_contract, operator_account, w3, store):
    logger.info("POLLING: durable scan resumes at block %s", store.next_block)

    def serve(event_id, args):
        btc_address = args["btcAddress"]
        balance = get_address_balance(btc_address)
        send_update(oracle_contract, operator_account, w3, btc_address, balance, store, event_id)

    while True:
        try:
            scan_events(w3, oracle_contract, "UpdateRequested", "UpdateRequested(string,address,uint256)", store)
            process_pending(store, serve, logger)
        except Exception as exc:
            logger.error("Polling error; stored cursor/events retained: %s", exc)
        time.sleep(POLL_INTERVAL)


# ─── Entry point ─────────────────────────────────────────────────────────────
def main():
    load_dotenv(Path(__file__).with_name(".env"))
    blk_dat_dir = os.getenv("BLK_DAT_DIR", "../../bitcoin")
    if not os.path.isabs(blk_dat_dir):
        blk_dat_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), blk_dat_dir))
    w3 = make_web3(os.getenv("ETH_RPC_URL", "http://127.0.0.1:8545"))
    require_local_chain(w3)
    oracle_addr = os.environ["ORACLE_ADDRESS"]
    operator_account = w3.eth.account.from_key(os.environ["OPERATOR_PRIVATE_KEY"])
    oracle_contract = w3.eth.contract(address=Web3.to_checksum_address(oracle_addr), abi=ORACLE_ABI)
    if not w3.eth.get_code(oracle_contract.address):
        raise RuntimeError("ORACLE_ADDRESS has no contract code on this chain; run setup first")
    if not os.path.isdir(blk_dat_dir):
        raise RuntimeError(f"Bitcoin directory not found: {blk_dat_dir}. Supply the first 131,000 mainnet blocks.")
    # Create/reopen the cursor BEFORE the potentially long Bitcoin sync. Scan
    # from deployment, never from the head observed after finishing the sync.
    database = os.getenv("EVENT_DB_PATH", str(Path(__file__).with_name(f"events-{oracle_addr.lower()}.sqlite3")))
    store = EventStore(database, store_identity(w3, oracle_addr, operator_account.address),
                       int(os.getenv("DEPLOYMENT_BLOCK", "0")))
    try:
        sync_bitcoin_blocks(blk_dat_dir)
        logger.info("ORACLE READY: Bitcoin sync complete. You can now run simulate.py.")
        run_polling_loop(oracle_contract, operator_account, w3, store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
