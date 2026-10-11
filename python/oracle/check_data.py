"""Validate the required Bitcoin snapshot offline, without keys or an Ethereum node."""

import argparse
import json
from pathlib import Path

from btc_utils import BlockDataError
import oracle_service as oracle


def check_snapshot(data_dir, summary=False, addresses=()):
    """Return a report only after a complete 131,000-block replay succeeds."""
    data_dir = Path(data_dir).resolve()
    try:
        oracle.sync_bitcoin_blocks(str(data_dir))
    except BlockDataError as exc:
        return {
            "valid": False,
            "data_dir": str(data_dir),
            "required_blocks": oracle.MAX_BLOCKS,
            "balances_available": False,
            "error": str(exc),
        }

    report = {
        "valid": True,
        "data_dir": str(data_dir),
        "blocks": oracle.MAX_BLOCKS,
        "last_height": oracle.MAX_BLOCKS - 1,
        "utxo_count": len(oracle.utxo_set),
        "address_count": len(oracle.addr_utxos),
        "balances_available": True,
    }
    if addresses:
        report["requested_addresses"] = [
            {"address": address, "satoshi": oracle.get_address_balance(address)}
            for address in addresses
        ]
    if summary:
        candidates = sorted(
            ((address, sum(outputs.values())) for address, outputs in oracle.addr_utxos.items()),
            key=lambda item: (-item[1], item[0]),
        )[:5]
        report["example_addresses"] = [
            {
                "address": address,
                "satoshi": balance,
                "loan_capacity_wei_at_30_eth_per_btc": balance * 30 * 10**18 // 100_000_000,
            }
            for address, balance in candidates
        ]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[2] / "bitcoin")
    parser.add_argument("--summary", action="store_true", help="List five funded addresses after successful validation")
    parser.add_argument("--address", action="append", default=[], help="Report the historical balance of an address (repeatable)")
    args = parser.parse_args(argv)
    report = check_snapshot(args.data_dir, args.summary, args.address)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
