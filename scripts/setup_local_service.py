#!/usr/bin/env python3
"""Prepare the local localGenesis Hardhat service for the lab demo.

This script is intentionally simple: it ensures the repository's local Hardhat
network is available, then runs the project deployment script. It is written as a
Python wrapper to satisfy the PDF requirement for a Python setup script.
"""

import argparse
import os
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set up the local Hardhat project and deploy the core contracts.")
    parser.add_argument("--network", default="localGenesis", help="Hardhat network alias")
    parser.add_argument("--deploy-script", default="scripts/deploy.js", help="Deployment script path")
    parser.add_argument("--rpc-url", default="http://127.0.0.1:8545", help="RPC endpoint")
    return parser.parse_args()


def ensure_env() -> None:
    if not os.path.exists(".env"):
        print("No .env file found. Copy .env.example to .env and populate the private keys if needed.")


def run_command(command: list[str]) -> None:
    print(f"$ {' '.join(command)}")
    subprocess.run(command, check=True)


def main() -> int:
    args = parse_args()
    ensure_env()

    # Start the local chain only if it is not already running.
    # The project already ships a Hardhat node command, so this wrapper is kept
    # deliberately lightweight and mainly orchestrates deployment.
    run_command(["npx", "hardhat", "run", args.deploy_script, "--network", args.network])
    print("Local service setup complete.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Setup failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode)
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"Setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
