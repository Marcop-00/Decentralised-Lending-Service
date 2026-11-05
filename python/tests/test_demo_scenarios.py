"""Check the demo's default assertions without RPC, keys or real waiting."""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, PropertyMock, patch

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
spec = importlib.util.spec_from_file_location("scenario_simulation", PYTHON_ROOT / "simulate.py")
simulation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulation)


class DefaultDemoTests(unittest.TestCase):
    def setUp(self):
        self.before = {
            "owed": 500, "locked": 500, "contributed": 50000,
            "disposable": 49500, "pool_disposable": 49500, "reserve": 25,
            "failed_count": 0, "collateral": 45, "active": 1,
            "failed": False, "resolved": False, "status": 1, "cash": 49525,
        }
        self.after = dict(self.before, owed=475, locked=475, contributed=49975,
                          reserve=0, failed_count=1, collateral=50, active=0,
                          failed=True, resolved=True, status=3, cash=49500)
        self.pool = Mock()
        self.loan = SimpleNamespace(address="0xloan")
        self.contributor = SimpleNamespace(address="0xContributor")

    def claim(self, before, after, paid):
        event = {"args": {"contributor": "0xcontributor", "amount": paid}}
        self.pool.events.CompensationRequested.return_value.process_receipt.return_value = [event]
        with patch.object(simulation, "compensation_state", side_effect=[before, after]), \
                patch.object(simulation, "send_tx", return_value={"status": 1}) as send, \
                patch("builtins.print"):
            result = simulation.claim_demo_compensation(Mock(), self.pool, self.loan, 2, self.contributor)
        send.assert_called_once()
        self.pool.functions.requestCompensation.assert_called_with("0xloan")
        return result

    def test_partial_compensation_is_capped_by_the_available_reserve(self):
        self.assertEqual(self.claim(self.before, self.after, 25), 25)

    def test_first_claim_with_empty_reserve_still_records_default(self):
        before = dict(self.before, reserve=0, cash=49500)
        after = dict(before, failed_count=1, collateral=50, active=0,
                     failed=True, resolved=True, status=3)
        self.assertEqual(self.claim(before, after, 0), 0)

    def test_retry_does_not_count_the_same_default_again(self):
        self.assertEqual(self.claim(self.after, dict(self.after), 0), 0)

    def test_demo_rejects_a_payout_inconsistent_with_the_event(self):
        with self.assertRaisesRegex(RuntimeError, "paid amount"):
            self.claim(self.before, self.after, 24)

    def test_demo_rejects_compensation_becoming_a_second_withdrawal_claim(self):
        wrong = dict(self.after, disposable=self.after["disposable"] + 25)
        with self.assertRaisesRegex(RuntimeError, "disposable unchanged"):
            self.claim(self.before, wrong, 25)

    def test_expiry_requires_a_block_strictly_after_the_deadline(self):
        eth = Mock()
        type(eth).block_number = PropertyMock(side_effect=[100, 101])
        loan = Mock()
        loan.functions.dueBlock.return_value.call.return_value = 100
        with patch.object(simulation.time, "sleep") as sleep:
            simulation.wait_for_expiry(SimpleNamespace(eth=eth), loan, 5)
        sleep.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
