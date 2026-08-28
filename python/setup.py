import json
import os
import time
from pathlib import Path

from web3 import Web3


def main():
    print("⚙️  Connecting to local Geth node...")
    w3 = Web3(Web3.HTTPProvider('http://127.0.0.1:8545'))
    
    if not w3.is_connected():
        print("❌ Failed to connect to node at http://127.0.0.1:8545")
        return

    PREFUNDED_ADDRESS = Web3.to_checksum_address("0xd278d247a52c550508ea2b2c9321d816238fb523")
    
    print("⚙️  Generating new accounts for the system...")
    deployer = w3.eth.account.create()
    contributor = w3.eth.account.create()
    borrower = w3.eth.account.create()

    print(f"- New Deployer: {deployer.address}")
    print(f"- New Contributor: {contributor.address}")
    print(f"- New Borrower: {borrower.address}")

    print("\n💸 Transferring funds from pre-funded account to new accounts...")
    
    fund_amount = w3.to_wei(100, 'ether')
    
    # Read the keystore to sign offline
    import glob
    keystore_files = glob.glob("private-chain/keystore/UTC--*")
    if not keystore_files:
        print("❌ Could not find pre-funded account keystore")
        return
    
    with open(keystore_files[0], "r") as f:
        keyfile = f.read()
    with open("private-chain/password.txt", "r") as f:
        pwd = f.read().strip()
    
    prefunded_key = w3.eth.account.decrypt(keyfile, pwd)
    prefunded_account = w3.eth.account.from_key(prefunded_key)
    
    base_nonce = w3.eth.get_transaction_count(prefunded_account.address, 'pending')
    
    def fund_account(to_address, nonce):
        tx = {
            "to": to_address,
            "value": fund_amount,
            "nonce": nonce,
            "gas": 21000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 202526
        }
        signed_tx = w3.eth.account.sign_transaction(tx, prefunded_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        return tx_hash.hex()

    fund_account(deployer.address, base_nonce)
    fund_account(contributor.address, base_nonce + 1)
    last_tx_hash = fund_account(borrower.address, base_nonce + 2)
    
    print("⏳ Waiting for the funding transactions to be mined...")
    w3.eth.wait_for_transaction_receipt(last_tx_hash)
    
    print("\n🚀 Starting contract deployment with the new Deployer account...")
    
    def deploy_contract(contract_name, *args):
        artifact_path = Path(f"artifacts/contracts/{contract_name}.sol/{contract_name}.json")
        with open(artifact_path, "r") as f:
            artifact = json.load(f)
        
        Contract = w3.eth.contract(abi=artifact['abi'], bytecode=artifact['bytecode'])
        
        nonce = w3.eth.get_transaction_count(deployer.address, 'pending')
        tx = Contract.constructor(*args).build_transaction({
            'from': deployer.address,
            'nonce': nonce,
            'gasPrice': w3.eth.gas_price
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=deployer.key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        return tx_receipt.contractAddress, artifact['abi']

    # Deploy BitcoinOracle. Its minimum update fee is fixed in the contract as
    # the update gas estimate times 0.1 gwei, as required by the trace.
    oracle_address, _ = deploy_contract("BitcoinOracle")
    print(f"✅ BitcoinOracle deployed at: {oracle_address}")

    # Deploy the UUPS implementation and its ERC-1967 proxy. The proxy
    # constructor initialises the pool atomically, so no account can take it over.
    implementation_address, pool_abi = deploy_contract("FundingPool")
    pool_address, _ = deploy_contract("FundingPoolProxy", implementation_address, oracle_address)
    print(f"✅ FundingPool implementation deployed at: {implementation_address}")
    print(f"✅ FundingPool proxy deployed and initialized at: {pool_address}")

    print("\n⚙️  Automatic generation of .env files...")
    env_content = f"""ETH_RPC_URL=http://127.0.0.1:8545
ORACLE_ADDRESS={oracle_address}
POOL_ADDRESS={pool_address}
OPERATOR_PRIVATE_KEY={deployer.key.hex()}
VOTER_PRIVATE_KEY={contributor.key.hex()}
BORROWER_PRIVATE_KEY={borrower.key.hex()}
BLK_DAT_DIR=../../bitcoin
"""

    os.makedirs(os.path.join(os.getcwd(), "python", "oracle"), exist_ok=True)
    os.makedirs(os.path.join(os.getcwd(), "python", "voter"), exist_ok=True)

    with open(os.path.join(os.getcwd(), "python", "oracle", ".env"), "w") as f:
        f.write(env_content)
    with open(os.path.join(os.getcwd(), "python", "voter", ".env"), "w") as f:
        f.write(env_content)
    with open(os.path.join(os.getcwd(), "python", ".env"), "w") as f:
        f.write(env_content)

    print("✅ Setup Complete! The infrastructure is ready.")

if __name__ == "__main__":
    main()
