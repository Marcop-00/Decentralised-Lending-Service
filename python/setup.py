"""Create fresh service accounts and deploy on the course's private chain."""

import json
import os
from pathlib import Path
import subprocess
import tempfile

from web3 import Web3

from durable_events import checked_receipt, make_web3, require_local_chain

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREFUNDED_ADDRESS = "0xd278d247a52c550508ea2b2c9321d816238fb523"


def select_prefunded_keystore(directory, address=PREFUNDED_ADDRESS):
    matches = sorted(path for path in Path(directory).glob("UTC--*")
                     if path.name.lower().endswith(address.lower().removeprefix("0x")))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one keystore for the provided prefunded address; found {len(matches)}")
    return matches[0]


def write_private_env(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".env-", text=True)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    # Coverage writes instrumented artifacts to the same directory. Rebuild
    # ordinary bytecode before creating accounts or sending any transaction.
    subprocess.run(["npm", "run", "compile"], cwd=PROJECT_ROOT, check=True)
    rpc_url = os.getenv("ETH_RPC_URL", "http://127.0.0.1:8545")
    w3 = make_web3(rpc_url)
    require_local_chain(w3)

    # The supplied account is used EXCLUSIVELY for ordinary value transfers.
    keyfile = select_prefunded_keystore(PROJECT_ROOT / "private-chain/keystore").read_text()
    password = (PROJECT_ROOT / "private-chain/password.txt").read_text().strip()
    prefunded_key = w3.eth.account.decrypt(keyfile, password)
    prefunded = w3.eth.account.from_key(prefunded_key)
    if prefunded.address.lower() != PREFUNDED_ADDRESS.lower():
        raise RuntimeError("Keystore does not contain the required prefunded account")

    deployer, contributor, borrower = (w3.eth.account.create() for _ in range(3))
    accounts = {"Deployer": deployer, "Contributor": contributor, "Borrower": borrower}
    for role, account in accounts.items():
        transaction = {
            "to": account.address, "value": w3.to_wei(100, "ether"),
            "nonce": w3.eth.get_transaction_count(prefunded.address, "pending"),
            "gas": 21_000, "gasPrice": w3.eth.gas_price, "chainId": 202526,
        }
        signed = prefunded.sign_transaction(transaction)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        checked_receipt(w3.eth.wait_for_transaction_receipt(tx_hash))
        print(f"{role}: {account.address}; balance={w3.from_wei(w3.eth.get_balance(account.address), 'ether')} ETH")

    def deploy_contract(contract_name, *arguments):
        artifact_path = PROJECT_ROOT / f"artifacts/contracts/{contract_name}.sol/{contract_name}.json"
        artifact = json.loads(artifact_path.read_text())
        factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        transaction = factory.constructor(*arguments).build_transaction({
            "from": deployer.address,
            "nonce": w3.eth.get_transaction_count(deployer.address, "pending"),
            "gasPrice": w3.eth.gas_price, "chainId": 202526,
        })
        signed = deployer.sign_transaction(transaction)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = checked_receipt(w3.eth.wait_for_transaction_receipt(tx_hash))
        address = receipt.get("contractAddress")
        if not address or not w3.eth.get_code(address):
            raise RuntimeError(f"Deployment of {contract_name} did not create contract code")
        print(f"{contract_name}: {address}; deployer balance={w3.from_wei(w3.eth.get_balance(deployer.address), 'ether')} ETH")
        return address, int(receipt["blockNumber"])

    oracle_address, deployment_block = deploy_contract("BitcoinOracle")
    implementation_address, _ = deploy_contract("FundingPool")
    pool_address, _ = deploy_contract("FundingPoolProxy", implementation_address, oracle_address)
    pool_artifact = json.loads((PROJECT_ROOT / "artifacts/contracts/FundingPool.sol/FundingPool.json").read_text())
    pool = w3.eth.contract(address=pool_address, abi=pool_artifact["abi"])
    if pool.functions.owner().call().lower() != deployer.address.lower():
        raise RuntimeError("Proxy initialization did not assign the expected owner")
    if pool.functions.bitcoinOracle().call().lower() != oracle_address.lower():
        raise RuntimeError("Proxy initialization did not set the expected oracle")

    env_content = f"""ETH_RPC_URL={rpc_url}
ORACLE_ADDRESS={oracle_address}
POOL_ADDRESS={pool_address}
DEPLOYMENT_BLOCK={deployment_block}
OPERATOR_PRIVATE_KEY={deployer.key.hex()}
VOTER_PRIVATE_KEY={contributor.key.hex()}
BORROWER_PRIVATE_KEY={borrower.key.hex()}
BLK_DAT_DIR={Path(os.getenv('BLK_DAT_DIR', str(PROJECT_ROOT / 'bitcoin'))).resolve()}
BTC_ADDRESS={os.getenv('BTC_ADDRESS', '')}
"""
    for relative_path in ("python/.env", "python/oracle/.env", "python/voter/.env"):
        write_private_env(PROJECT_ROOT / relative_path, env_content)
    print(f"Setup complete. Event services start scanning at deployment block {deployment_block}.")
    print("Start the oracle and voter, then run simulate.py with a BTC address from the complete dataset.")


if __name__ == "__main__":
    main()
