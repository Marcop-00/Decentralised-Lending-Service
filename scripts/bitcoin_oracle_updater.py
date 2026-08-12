#!/usr/bin/env python3
"""Simulate the off-chain Bitcoin liquidity oracle updating the on-chain oracle.

The PDF requires the off-chain oracle to process new blocks one by one and update
Ethereum with the latest Bitcoin address balances, while only scanning the first
131000 Bitcoin blocks. This script keeps that behavior lightweight and explicit:
- define a list of Bitcoin addresses to monitor,
- iterate over a simulated block range,
- compute a deterministic balance for each address,
- send the balance update to the Ethereum oracle contract via Hardhat/Node.

Usage:
    python3 scripts/bitcoin_oracle_updater.py --oracle 0x... --start 1 --end 131000
"""

import argparse
import json
import os
import subprocess
import sys
from typing import List


DEFAULT_ADDRESSES = [
    "bc1qexampleaddr1",
    "bc1qexampleaddr2",
    "tb1qexampleaddr3",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate the Bitcoin oracle and push balance updates to the Ethereum Oracle contract.")
    parser.add_argument("--oracle", required=True, help="Ethereum address of the BitcoinOracle contract")
    parser.add_argument("--start", type=int, default=1, help="Starting simulated Bitcoin block number")
    parser.add_argument("--end", type=int, default=131000, help="Ending simulated Bitcoin block number (default: 131000)")
    parser.add_argument("--addresses", nargs="*", default=DEFAULT_ADDRESSES, help="Bitcoin addresses to update")
    parser.add_argument("--rpc-url", default="http://127.0.0.1:8545", help="Ethereum JSON-RPC URL")
    parser.add_argument("--fee-wei", default="1000000000000000", help="Wei value to attach to each oracle update")
    return parser.parse_args()


def compute_balance(address: str, block_number: int) -> int:
    """Deterministic pseudo-balance used for the educational simulation.
    The project PDF only requires the off-chain logic to be designed as if blocks
    were generated one by one; this keeps the code compatible with a local demo.
    """
    seed = sum(ord(ch) for ch in address)
    base = (seed * 7 + block_number * 11) % 1_000_000_000
    return max(1_000_000, base)


def run_update(oracle: str, btc_address: str, balance_sats: int, fee_wei: str) -> None:
    cmd = [
        "node",
        "scripts/updateOracle.js",
        oracle,
        btc_address,
        str(balance_sats),
        fee_wei,
    ]
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    if args.start <= 0 or args.end < args.start:
        raise ValueError("--start must be > 0 and --end must be >= --start")

    print(f"Processing simulated Bitcoin blocks {args.start}..{args.end} for {len(args.addresses)} tracked addresses.")
    print(f"Oracle contract: {args.oracle}")

    for block_number in range(args.start, args.end + 1):
        for btc_address in args.addresses:
            balance_sats = compute_balance(btc_address, block_number)
            run_update(args.oracle, btc_address, balance_sats, args.fee_wei)

    print("Bitcoin oracle updates complete.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Oracle update failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode)
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"Oracle update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
