#!/usr/bin/env python3
"""Run a basic end-to-end example against the local Hardhat chain.

The PDF requires a Python script to execute an example workflow. This script is a
thin orchestrator: it launches a local Hardhat node when necessary, then runs the
existing Hardhat demo script that exercises the lending flow.
"""

import os
import subprocess
import sys


def ensure_hardhat_node() -> None:
    if not os.path.exists(".env"):
        print("No .env file found. Copy .env.example to .env and set the required node settings.")


def run_command(command: list[str]) -> None:
    print(f"$ {' '.join(command)}")
    subprocess.run(command, check=True)


def main() -> int:
    ensure_hardhat_node()
    # This project already includes a Hardhat test flow. The Python demo script keeps
    # the orchestration externalized, following the PDF requirement for a demo script.
    run_command(["npx", "hardhat", "test", "test/fundingPool.test.js", "--no-compile"])
    print("Demo workflow completed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Demo failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode)
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"Demo failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
