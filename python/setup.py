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
    
    # We send funds using the raw RPC method eth_sendTransaction since the private key is in Geth
    def fund_account(to_address):
        tx_hash = w3.provider.make_request("eth_sendTransaction", [{
            "from": PREFUNDED_ADDRESS,
            "to": to_address,
            "value": hex(fund_amount)
        }])
        return tx_hash['result']

    fund_account(deployer.address)
    fund_account(contributor.address)
    fund_account(borrower.address)
    
    print("⏳ Waiting for the funding transaction to be mined (about 10 seconds)...")
    time.sleep(12)
    
    print("\n🚀 Starting contract deployment with the new Deployer account...")
    
    def deploy_contract(contract_name, *args):
        artifact_path = Path(f"artifacts/contracts/{contract_name}.sol/{contract_name}.json")
        with open(artifact_path, "r") as f:
            artifact = json.load(f)
        
        Contract = w3.eth.contract(abi=artifact['abi'], bytecode=artifact['bytecode'])
        
        nonce = w3.eth.get_transaction_count(deployer.address)
        tx = Contract.constructor(*args).build_transaction({
            'from': deployer.address,
            'nonce': nonce,
            'gasPrice': w3.eth.gas_price
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=deployer.key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        return tx_receipt.contractAddress, artifact['abi']

    # Deploy BitcoinOracle
    min_fee = w3.to_wei(0.001, 'ether')
    oracle_address, _ = deploy_contract("BitcoinOracle", min_fee)
    print(f"✅ BitcoinOracle deployed at: {oracle_address}")

    # Deploy FundingPool
    pool_address, pool_abi = deploy_contract("FundingPool")
    print(f"✅ FundingPool deployed at: {pool_address}")

    # Initialize FundingPool
    Pool = w3.eth.contract(address=pool_address, abi=pool_abi)
    nonce = w3.eth.get_transaction_count(deployer.address)
    init_tx = Pool.functions.initialize(oracle_address).build_transaction({
        'from': deployer.address,
        'nonce': nonce,
        'gasPrice': w3.eth.gas_price
    })
    signed_init_tx = w3.eth.account.sign_transaction(init_tx, private_key=deployer.key)
    w3.eth.send_raw_transaction(signed_init_tx.raw_transaction)
    w3.eth.wait_for_transaction_receipt(signed_init_tx.hash)
    print("✅ FundingPool initialized")

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
