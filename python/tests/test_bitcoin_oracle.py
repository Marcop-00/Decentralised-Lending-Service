"""Offline regression tests: no RPC, environment files, keys or mainnet downloads."""

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))

import bitcoin
from bitcoin.core import CBlock, CMutableTransaction, CMutableTxIn, CMutableTxOut, COutPoint, b2lx
from bitcoin.core.script import CScript, OP_CHECKSIG, OP_DUP, OP_EQUALVERIFY, OP_HASH160

import btc_utils as parser
import oracle_service as oracle
import check_data


GENESIS = bitcoin.params.GENESIS_BLOCK
SCRIPT = CScript([OP_DUP, OP_HASH160, b"\x11" * 20, OP_EQUALVERIFY, OP_CHECKSIG])


def make_block(parent=GENESIS, tag=1, transactions=None):
    """Synthetic linked blocks, for parser/index tests (not mined consensus blocks)."""
    if transactions is None:
        transactions = [CMutableTransaction(
            vin=[CMutableTxIn(scriptSig=CScript([bytes([tag])]))],
            vout=[CMutableTxOut(50 * 100_000_000, SCRIPT)],
        )]
    provisional = CBlock(vtx=transactions)
    return CBlock(
        nVersion=1, hashPrevBlock=parent.GetHash(),
        hashMerkleRoot=provisional.calc_merkle_root(), nTime=parent.nTime + 600,
        nBits=GENESIS.nBits, nNonce=tag, vtx=transactions,
    )


def record(block):
    payload = block.serialize()
    return parser.MAINNET_MAGIC + struct.pack("<I", len(payload)) + payload


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / "blk00000.dat"

    def test_mainnet_genesis_counts_as_block_zero(self):
        self.file.write_bytes(record(GENESIS))
        blocks = list(parser.parse_blocks(self.directory.name, max_blocks=1))
        self.assertEqual([(h, b.GetHash()) for h, b in blocks], [(0, parser.MAINNET_GENESIS_HASH)])

    def test_wrong_genesis_is_rejected(self):
        wrong = CBlock(nBits=GENESIS.nBits)
        self.file.write_bytes(record(wrong))
        with self.assertRaisesRegex(parser.BlockDataError, "mainnet genesis"):
            list(parser.parse_blocks(self.directory.name, max_blocks=1))

    def test_missing_files_are_rejected(self):
        with self.assertRaisesRegex(parser.BlockDataError, "No blk.dat"):
            list(parser.parse_blocks(self.directory.name, max_blocks=1))

    def test_incomplete_chain_is_rejected_before_yielding(self):
        self.file.write_bytes(record(GENESIS))
        with self.assertRaisesRegex(parser.BlockDataError, "found 1 connected blocks; need 2"):
            next(parser.parse_blocks(self.directory.name, max_blocks=2))

    def test_corrupt_record_does_not_silently_end_sync(self):
        self.file.write_bytes(record(GENESIS) + b"BAD!" + bytes(100))
        with self.assertRaisesRegex(parser.BlockDataError, "Unexpected magic"):
            list(parser.parse_blocks(self.directory.name, max_blocks=1))

    def test_truncated_record_is_rejected(self):
        for tail in (b"\xf9", parser.MAINNET_MAGIC + b"\x01", record(GENESIS)[:-1]):
            with self.subTest(tail_length=len(tail)):
                self.file.write_bytes(tail)
                with self.assertRaisesRegex(parser.BlockDataError, "Truncated"):
                    list(parser.parse_blocks(self.directory.name, max_blocks=1))

    def test_merkle_root_detects_corrupt_transaction(self):
        corrupt = bytearray(record(GENESIS))
        corrupt[-1] ^= 1  # Change the transaction locktime, leaving the header intact.
        self.file.write_bytes(corrupt)
        with self.assertRaisesRegex(parser.BlockDataError, "integrity check"):
            list(parser.parse_blocks(self.directory.name, max_blocks=1))

    def test_chain_order_and_exact_limit(self):
        first = make_block()
        second = make_block(first, 2)
        self.file.write_bytes(record(second) + record(GENESIS) + record(first))
        blocks = list(parser.parse_blocks(self.directory.name, max_blocks=2))
        self.assertEqual([h for h, _ in blocks], [0, 1])
        self.assertEqual([b.GetHash() for _, b in blocks], [GENESIS.GetHash(), first.GetHash()])

    def test_only_zero_padding_is_allowed(self):
        self.file.write_bytes(record(GENESIS) + bytes(20))
        self.assertEqual(len(list(parser.parse_blocks(self.directory.name, max_blocks=1))), 1)
        self.file.write_bytes(record(GENESIS) + bytes(20) + b"nonzero")
        with self.assertRaisesRegex(parser.BlockDataError, "after padding"):
            list(parser.parse_blocks(self.directory.name, max_blocks=1))


class UtxoTests(unittest.TestCase):
    def setUp(self):
        oracle.utxo_set.clear()
        oracle.addr_utxos.clear()
        self.addCleanup(oracle.utxo_set.clear)
        self.addCleanup(oracle.addr_utxos.clear)

    def test_genesis_reward_is_never_available_liquidity(self):
        oracle.process_block(GENESIS, 0)
        self.assertEqual(oracle.utxo_set, {})
        self.assertEqual(oracle.get_address_balance("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"), 0)

    def test_wrong_height_zero_is_rejected(self):
        with self.assertRaisesRegex(parser.BlockDataError, "mainnet genesis"):
            oracle.process_block(make_block(), 0)

    def test_outputs_can_be_spent_by_a_later_block(self):
        first = make_block()
        oracle.process_block(first, 1)
        original = first.vtx[0]
        payment = CMutableTransaction(
            vin=[CMutableTxIn(COutPoint(original.GetTxid(), 0))],
            vout=[CMutableTxOut(2_000, SCRIPT)],
        )
        second = make_block(first, 2, [payment])
        oracle.process_block(second, 2)
        self.assertNotIn((b2lx(original.GetTxid()), 0), oracle.utxo_set)
        self.assertEqual(oracle.get_address_balance(parser.script_to_address(SCRIPT)), 2_000)

    def test_failed_block_leaves_both_indexes_unchanged(self):
        oracle._add_utxo("existing", 0, "original-address", 123)
        first = make_block()
        second = make_block(first, 2)
        mixed = SimpleNamespace(vtx=[first.vtx[0], second.vtx[0]])
        before_utxos = dict(oracle.utxo_set)
        before_addresses = {a: dict(v) for a, v in oracle.addr_utxos.items()}
        with patch.object(oracle, "script_to_address", side_effect=["new-address", ValueError("malformed output")]):
            with self.assertRaisesRegex(ValueError, "malformed output"):
                oracle.process_block(mixed, 3)
        self.assertEqual(oracle.utxo_set, before_utxos)
        self.assertEqual(dict(oracle.addr_utxos), before_addresses)

    def test_replacing_an_outpoint_keeps_indexes_consistent(self):
        oracle._add_utxo("duplicate", 0, "old-address", 123)
        oracle._add_utxo("duplicate", 0, "new-address", 456)
        self.assertEqual(oracle.get_address_balance("old-address"), 0)
        self.assertEqual(oracle.get_address_balance("new-address"), 456)
        self.assertNotIn("old-address", oracle.addr_utxos)

    def test_incomplete_sync_discards_partial_state(self):
        blocks = [(0, GENESIS), (1, make_block())]
        with patch.object(oracle, "MAX_BLOCKS", 3), patch.object(oracle, "parse_blocks", return_value=iter(blocks)):
            with self.assertRaisesRegex(parser.BlockDataError, "processed 2/3"):
                oracle.sync_bitcoin_blocks("unused")
        self.assertEqual(oracle.utxo_set, {})
        self.assertEqual(dict(oracle.addr_utxos), {})

    def test_nonconsecutive_height_aborts_sync(self):
        blocks = [(0, GENESIS), (2, make_block())]
        with patch.object(oracle, "MAX_BLOCKS", 2), patch.object(oracle, "parse_blocks", return_value=iter(blocks)):
            with self.assertRaisesRegex(parser.BlockDataError, "Unexpected Bitcoin block height 2"):
                oracle.sync_bitcoin_blocks("unused")
        self.assertEqual(oracle.utxo_set, {})

    def test_valid_sync_processes_exactly_the_requested_snapshot(self):
        blocks = [(0, GENESIS), (1, make_block())]
        with patch.object(oracle, "MAX_BLOCKS", 2), patch.object(oracle, "parse_blocks", return_value=iter(blocks)) as parse:
            oracle.sync_bitcoin_blocks("unused")
        parse.assert_called_once_with("unused", max_blocks=2)
        self.assertEqual(len(oracle.utxo_set), 1)
        self.assertEqual(oracle.get_address_balance("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"), 0)


class PreflightTests(unittest.TestCase):
    def tearDown(self):
        oracle.utxo_set.clear()
        oracle.addr_utxos.clear()

    def test_incomplete_data_never_reports_usable_addresses(self):
        with patch.object(oracle, "sync_bitcoin_blocks", side_effect=parser.BlockDataError("missing blocks")):
            report = check_data.check_snapshot("unused", summary=True, addresses=["address"])
        self.assertFalse(report["valid"])
        self.assertFalse(report["balances_available"])
        self.assertNotIn("example_addresses", report)
        self.assertNotIn("requested_addresses", report)

    def test_summary_requires_successful_sync_and_uses_integer_units(self):
        def synced(_):
            oracle.utxo_set.clear()
            oracle.addr_utxos.clear()
            oracle._add_utxo("tx", 0, "address", 100_000_000)

        with patch.object(oracle, "sync_bitcoin_blocks", side_effect=synced):
            report = check_data.check_snapshot("unused", summary=True, addresses=["address"])
        self.assertTrue(report["valid"])
        self.assertEqual(report["blocks"], 131_000)
        self.assertEqual(report["last_height"], 130_999)
        self.assertEqual(report["example_addresses"][0]["loan_capacity_wei_at_30_eth_per_btc"], 30 * 10**18)
        self.assertEqual(report["requested_addresses"][0]["satoshi"], 100_000_000)


if __name__ == "__main__":
    unittest.main()
