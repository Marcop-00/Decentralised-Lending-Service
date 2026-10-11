"""Offline regression tests: no RPC connections, dotenv loads or real keys."""

import importlib.util
import logging
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from durable_events import (
    EventStore, PermanentEventError, checked_receipt, make_web3, process_pending,
    require_local_chain, scan_events, send_durable,
)
from web3 import Web3
from web3.exceptions import TransactionNotFound


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


voter = load_module("audit_voter", PYTHON_ROOT / "voter/auto_voter.py")
setup = load_module("audit_setup", PYTHON_ROOT / "setup.py")
simulation = load_module("audit_simulation", PYTHON_ROOT / "simulate.py")


class DurableEventsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "events.sqlite3"
        self.store = EventStore(self.path, "test-chain:contract:account", 2)
        self.logger = Mock(spec=logging.Logger)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def reopen(self):
        self.store.close()
        self.store = EventStore(self.path, "test-chain:contract:account", 999)

    def enqueue(self):
        self.store.enqueue_scan([("tx:0", 4, {"btcAddress": "test"})], 8)

    def make_w3(self):
        eth = Mock()
        eth.chain_id = 202526
        eth.gas_price = 100_000_000
        eth.get_transaction_count.return_value = 7
        eth.get_block.return_value = {"hash": b"checkpoint"}
        eth.get_transaction_receipt.side_effect = TransactionNotFound("pending")
        eth.wait_for_transaction_receipt.return_value = {"status": 1, "blockNumber": 10}
        return SimpleNamespace(eth=eth, keccak=Web3.keccak, to_hex=Web3.to_hex)

    def test_startup_scans_from_deployment_and_restart_preserves_events(self):
        w3 = self.make_w3()
        w3.eth.block_number = 10
        w3.eth.get_logs.return_value = [{"transactionHash": b"tx", "logIndex": 0, "blockNumber": 4}]
        contract = Mock()
        contract.address = "0xcontract"
        contract.events.UpdateRequested.return_value.process_log.return_value = {"args": {"btcAddress": "test"}}
        scan_events(w3, contract, "UpdateRequested", "UpdateRequested(string,address,uint256)", self.store)
        query = w3.eth.get_logs.call_args.args[0]
        self.assertEqual(query["fromBlock"], 2)
        self.assertEqual(query["toBlock"], 10)
        self.reopen()
        self.assertEqual(self.store.next_block, 11)
        self.assertEqual(len(self.store.pending()), 1)

    def test_failed_fetch_or_decode_does_not_advance_cursor(self):
        w3 = self.make_w3()
        w3.eth.block_number = 10
        w3.eth.get_logs.side_effect = OSError("offline")
        with self.assertRaises(OSError):
            scan_events(w3, Mock(), "UpdateRequested", "signature", self.store)
        self.assertEqual(self.store.next_block, 2)
        w3.eth.get_logs.side_effect = None
        w3.eth.get_logs.return_value = [{"transactionHash": b"tx", "logIndex": 0, "blockNumber": 4}]
        contract = Mock()
        contract.events.UpdateRequested.return_value.process_log.side_effect = ValueError("cannot decode")
        with self.assertRaises(ValueError):
            scan_events(w3, contract, "UpdateRequested", "signature", self.store)
        self.assertEqual(self.store.next_block, 2)

    def test_queue_and_cursor_commit_atomically(self):
        with self.assertRaises(TypeError):
            self.store.enqueue_scan([("valid", 4, {}), ("bad", 5, {"invalid": object()})], 8)
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.next_block, 2)

    def test_retry_survives_restart_and_does_not_lose_later_events(self):
        self.store.enqueue_scan([("first", 4, {}), ("second", 5, {})], 8)
        failing = Mock(side_effect=OSError("RPC unavailable"))
        process_pending(self.store, failing, self.logger)
        self.assertEqual(failing.call_count, 1)
        self.reopen()
        self.assertEqual(len(self.store.pending()), 2)
        healthy = Mock()
        process_pending(self.store, healthy, self.logger)
        self.assertEqual(healthy.call_count, 2)
        self.assertEqual(self.store.pending(), [])
        # Replaying the same log after a crash cannot create another request.
        self.store.enqueue_scan([("first", 4, {})], 8)
        self.assertEqual(self.store.pending(), [])

    def test_outbox_recovers_mined_transaction_after_timeout_without_resending(self):
        self.enqueue()
        w3 = self.make_w3()
        account = Mock(address="0xaccount")
        account.sign_transaction.return_value.raw_transaction = b"signed-test-transaction"
        tx_call = Mock()
        tx_call.build_transaction.return_value = {"nonce": 7}
        w3.eth.wait_for_transaction_receipt.side_effect = TimeoutError("receipt delayed")
        with self.assertRaises(TimeoutError):
            send_durable(w3, account, tx_call, self.store, "tx:0")
        self.assertIsNotNone(self.store.get("tx:0")["tx_hash"])
        self.reopen()
        w3.eth.get_transaction_receipt.side_effect = None
        w3.eth.get_transaction_receipt.return_value = {"status": 1, "blockNumber": 10}
        receipt = send_durable(w3, account, tx_call, self.store, "tx:0")
        self.assertEqual(receipt["status"], 1)
        self.assertEqual(tx_call.build_transaction.call_count, 1)
        self.assertEqual(w3.eth.send_raw_transaction.call_count, 1)

    def test_failed_broadcast_retries_exact_signed_bytes(self):
        self.enqueue()
        w3 = self.make_w3()
        account = Mock(address="0xaccount")
        account.sign_transaction.return_value.raw_transaction = b"signed-test-transaction"
        tx_call = Mock()
        w3.eth.send_raw_transaction.side_effect = [OSError("offline"), b"hash"]
        with self.assertRaises(OSError):
            send_durable(w3, account, tx_call, self.store, "tx:0")
        self.reopen()
        send_durable(w3, account, tx_call, self.store, "tx:0")
        calls = w3.eth.send_raw_transaction.call_args_list
        self.assertEqual(calls[0].args[0], calls[1].args[0])
        self.assertEqual(tx_call.build_transaction.call_count, 1)
        self.assertEqual(w3.eth.get_transaction_count.call_args.args[1], "pending")

    def test_reverted_receipt_is_not_success_and_allows_new_transaction(self):
        self.enqueue()
        w3 = self.make_w3()
        account = Mock(address="0xaccount")
        account.sign_transaction.return_value.raw_transaction = b"signed-test-transaction"
        w3.eth.wait_for_transaction_receipt.return_value = {"status": 0, "blockNumber": 10}
        with self.assertRaisesRegex(RuntimeError, "reverted"):
            send_durable(w3, account, Mock(), self.store, "tx:0")
        self.assertEqual(self.store.get("tx:0")["status"], "pending")
        self.assertIsNone(self.store.get("tx:0")["tx_hash"])

    def test_permanent_failure_is_retained_and_does_not_block_other_events(self):
        self.store.enqueue_scan([("closed", 4, {}), ("open", 5, {})], 8)
        handler = Mock(side_effect=[PermanentEventError("proposal closed"), None])
        process_pending(self.store, handler, self.logger)
        self.assertEqual(self.store.get("closed")["status"], "dead")
        self.assertIn("closed", self.store.get("closed")["last_error"])
        self.assertEqual(self.store.get("open")["status"], "done")

    def test_database_rejects_another_chain_or_contract(self):
        with self.assertRaisesRegex(ValueError, "another chain"):
            EventStore(self.path, "different-contract", 0)

    def test_reset_detected_even_after_chain_regrows_past_cursor(self):
        self.store.enqueue_scan([], 10, Web3.to_hex(b"original"))
        self.reopen()
        w3 = self.make_w3()
        w3.eth.block_number = 500
        with self.assertRaisesRegex(RuntimeError, "checkpoint changed"):
            scan_events(w3, Mock(), "UpdateRequested", "signature", self.store)
        self.assertEqual(self.store.next_block, 11)
        w3.eth.get_logs.assert_not_called()

    def test_chain_change_during_scan_keeps_cursor_and_events_unchanged(self):
        w3 = self.make_w3()
        w3.eth.block_number = 10
        w3.eth.get_block.side_effect = [{"hash": b"one"}, {"hash": b"two"}]
        w3.eth.get_logs.return_value = []
        with self.assertRaisesRegex(RuntimeError, "changed during event scan"):
            scan_events(w3, Mock(), "UpdateRequested", "signature", self.store)
        self.assertEqual(self.store.next_block, 2)
        self.assertIsNone(self.store.checkpoint_hash)

    def test_nonce_conflict_is_reported_without_infinite_wait_or_second_transaction(self):
        self.enqueue()
        w3 = self.make_w3()
        account = Mock(address="0xaccount")
        account.sign_transaction.return_value.raw_transaction = b"signed-test-transaction"
        tx_call = Mock()
        w3.eth.send_raw_transaction.side_effect = ValueError("nonce too low")
        handler = lambda event_id, _: send_durable(w3, account, tx_call, self.store, event_id)
        process_pending(self.store, handler, self.logger)
        self.assertEqual(self.store.get("tx:0")["status"], "dead")
        self.assertIn("Nonce conflict", self.store.get("tx:0")["last_error"])
        self.assertIsNotNone(self.store.get("tx:0")["raw_tx"])
        w3.eth.wait_for_transaction_receipt.assert_not_called()
        self.assertEqual(tx_call.build_transaction.call_count, 1)


class VoterTests(unittest.TestCase):
    def setUp(self):
        self.pool = Mock()
        self.account = SimpleNamespace(address="contributor")
        self.pool.functions.hasVoted.return_value.call.side_effect = [False, True]
        self.pool.functions.proposals.return_value.call.return_value = [0] * 8 + [False, "0x0"]
        self.pool.functions.terminated.return_value.call.return_value = False
        self.pool.functions.totalContributed.return_value.call.return_value = 100

    def test_fully_locked_contributor_still_votes_yes(self):
        with patch.object(voter, "send_durable", return_value={"status": 1, "blockNumber": 10}) as send:
            voter.evaluate_and_vote(self.pool, self.account, Mock(), 3, Mock(), "event")
        self.pool.functions.voteOnProposal.assert_called_once_with(3, True)
        self.pool.functions.unlockedBalanceOf.assert_not_called()
        send.assert_called_once()

    def test_already_voted_is_idempotent(self):
        self.pool.functions.hasVoted.return_value.call.side_effect = None
        self.pool.functions.hasVoted.return_value.call.return_value = True
        with patch.object(voter, "send_durable") as send:
            voter.evaluate_and_vote(self.pool, self.account, Mock(), 3, Mock(), "event")
        send.assert_not_called()

    def test_closed_proposal_is_explicit_permanent_failure(self):
        self.pool.functions.proposals.return_value.call.return_value = [0] * 8 + [True, "0x0"]
        with self.assertRaises(PermanentEventError):
            voter.evaluate_and_vote(self.pool, self.account, Mock(), 3, Mock(), "event")

    def test_existing_no_vote_is_reported_instead_of_claiming_yes(self):
        self.pool.functions.hasVoted.return_value.call.side_effect = None
        self.pool.functions.hasVoted.return_value.call.return_value = True
        self.pool.functions.voteSupport.return_value.call.return_value = False
        with self.assertRaisesRegex(PermanentEventError, "already has a NO"):
            voter.evaluate_and_vote(self.pool, self.account, Mock(), 3, Mock(), "event")

    def test_missing_contribution_is_retryable(self):
        self.pool.functions.totalContributed.return_value.call.return_value = 0
        with self.assertRaisesRegex(RuntimeError, "no pool contribution"):
            voter.evaluate_and_vote(self.pool, self.account, Mock(), 3, Mock(), "event")


class SetupAndDemoTests(unittest.TestCase):
    def test_failed_rebuild_stops_setup_before_rpc_or_funding(self):
        failure = setup.subprocess.CalledProcessError(1, ["npm", "run", "compile"])
        with patch.object(setup.subprocess, "run", side_effect=failure) as rebuild, \
                patch.object(setup, "make_web3") as provider:
            with self.assertRaises(setup.subprocess.CalledProcessError):
                setup.main()
        rebuild.assert_called_once_with(["npm", "run", "compile"], cwd=setup.PROJECT_ROOT, check=True)
        provider.assert_not_called()

    def test_provider_installs_clique_middleware_without_network_access(self):
        from web3.middleware import ExtraDataToPOAMiddleware
        w3 = make_web3("http://example.invalid")
        self.assertIs(w3.middleware_onion.get("course_poa"), ExtraDataToPOAMiddleware)

    def test_keystore_selection_uses_required_address_not_first_file(self):
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory) / ("UTC--later--" + setup.PREFUNDED_ADDRESS[2:])
            expected.write_text("not a secret: fixture never read by selection")
            (Path(directory) / "UTC--first--different-address").touch()
            self.assertEqual(setup.select_prefunded_keystore(directory), expected)

    def test_setup_refuses_wrong_chain_before_any_transaction(self):
        w3 = Mock()
        w3.is_connected.return_value = True
        w3.eth.chain_id = 1
        with self.assertRaisesRegex(RuntimeError, "202526"):
            require_local_chain(w3)
        w3.eth.send_raw_transaction.assert_not_called()

    def test_failed_transaction_receipt_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "reverted"):
            checked_receipt({"status": 0})

    def test_btc_requirement_rounds_up_at_satoshi_precision(self):
        self.assertEqual(simulation.required_satoshis(10**18), 3_333_334)
        self.assertEqual(simulation.required_satoshis(30 * 10**18), 100_000_000)

    def test_demo_waits_for_new_event_and_recognizes_zero_balance_response(self):
        request = {"blockNumber": 10, "transactionIndex": 1, "logIndex": 2}
        stale = {"blockNumber": 10, "transactionIndex": 0, "logIndex": 1,
                 "args": {"btcAddress": "target", "balanceInSatoshi": 100}}
        fresh = {"blockNumber": 11, "transactionIndex": 0, "logIndex": 0,
                 "args": {"btcAddress": "target", "balanceInSatoshi": 0}}
        oracle = Mock()
        oracle.events.BalanceUpdated.return_value.get_logs.side_effect = [[stale], [stale, fresh]]
        w3 = Mock()
        w3.eth.block_number = 11
        with patch.object(simulation.time, "sleep"):
            balance = simulation.wait_for_fresh_balance(w3, oracle, request, "target", 5)
        self.assertEqual(balance, 0)
        self.assertEqual(oracle.events.BalanceUpdated.return_value.get_logs.call_count, 2)


if __name__ == "__main__":
    unittest.main()
