import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3


def get_contract(w3, contract_name, address):
    artifact_path = Path(f"artifacts/contracts/{contract_name}.sol/{contract_name}.json")
    with open(artifact_path, "r") as f:
        artifact = json.load(f)
    return w3.eth.contract(address=address, abi=artifact['abi'])

def send_tx(w3, account, tx_call):
    nonce = w3.eth.get_transaction_count(account.address)
    tx = tx_call.build_transaction({
        'from': account.address,
        'nonce': nonce,
        'gasPrice': w3.eth.gas_price
    })
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(tx_hash)

def send_tx_with_value(w3, account, tx_call, value):
    nonce = w3.eth.get_transaction_count(account.address)
    tx = tx_call.build_transaction({
        'from': account.address,
        'nonce': nonce,
        'value': value,
        'gasPrice': w3.eth.gas_price
    })
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(tx_hash)

def print_balances(w3, pool, accounts):
    print("\n--- Current Balances ---")
    for name, acc in accounts.items():
        eth_bal = w3.from_wei(w3.eth.get_balance(acc.address), 'ether')
        if name == "Contributor":
            unlocked = w3.from_wei(pool.functions.unlockedBalanceOf(acc.address).call(), 'ether')
            locked = w3.from_wei(pool.functions.lockedContributions(acc.address).call(), 'ether')
            print(f"{name}: {eth_bal:.4f} ETH | Unlocked in Pool: {unlocked:.4f} ETH | Locked in Pool: {locked:.4f} ETH")
        else:
            print(f"{name}: {eth_bal:.4f} ETH")
    pool_bal = w3.from_wei(w3.eth.get_balance(pool.address), 'ether')
    print(f"FundingPool: {pool_bal:.4f} ETH")
    print(f"Pool disposable: {w3.from_wei(pool.functions.totalUnlockedFunds().call(), 'ether'):.4f} ETH")
    print(f"Compensation pool: {w3.from_wei(pool.functions.compensationPoolBalance().call(), 'ether'):.4f} ETH")
    print(f"Collateral percentage: {pool.functions.collateralPercentage().call()}% | Active loans: {pool.functions.activeLoanCount().call()}")
    print("------------------------\n")

def main():
    load_dotenv(os.path.join("python", ".env"))
    
    w3 = Web3(Web3.HTTPProvider(os.getenv("ETH_RPC_URL", "http://127.0.0.1:8545")))
    if not w3.is_connected():
        print("❌ Failed to connect to Web3 node")
        return

    pool_address = Web3.to_checksum_address(os.getenv("POOL_ADDRESS"))
    oracle_address = Web3.to_checksum_address(os.getenv("ORACLE_ADDRESS"))
    
    operator = w3.eth.account.from_key(os.getenv("OPERATOR_PRIVATE_KEY"))
    contributor = w3.eth.account.from_key(os.getenv("VOTER_PRIVATE_KEY"))
    borrower = w3.eth.account.from_key(os.getenv("BORROWER_PRIVATE_KEY"))

    pool = get_contract(w3, "FundingPool", pool_address)
    oracle = get_contract(w3, "BitcoinOracle", oracle_address)

    accounts = {
        "Deployer": operator,
        "Contributor": contributor,
        "Borrower": borrower
    }

    bitcoin_dir = Path(os.getenv("BLK_DAT_DIR", Path(__file__).resolve().parent.parent / "bitcoin"))
    if not bitcoin_dir.is_dir():
        print(f"❌ Bitcoin block directory not found: {bitcoin_dir}")
        print("   The full simulation requires the first 131,000 Bitcoin mainnet blocks for the real oracle.")
        return

    print("🚀 Starting Lending Flow Simulation...")
    print_balances(w3, pool, accounts)

    # 1. Contributor deposits funds
    unlocked = w3.from_wei(pool.functions.unlockedBalanceOf(contributor.address).call(), 'ether')
    if unlocked < 50:
        print(f"1. Contributor is depositing 50 ETH into the Funding Pool (current pool balance: {unlocked} ETH)...")
        send_tx_with_value(w3, contributor, pool.functions.contribute(), w3.to_wei(50, 'ether'))
        print("✅ Deposit successful!")
    else:
        print(f"1. Contributor already has {unlocked} ETH in the pool. Skipping deposit.")
    print_balances(w3, pool, accounts)

    # 2. Borrower creates loan proposal
    btc_address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    print("2. Borrower is creating a loan proposal (1 ETH at 5%)...")
    
    initial_proposal_count = pool.functions.proposalCount().call()
    
    send_tx(w3, borrower, pool.functions.createLoanProposal(
        borrower.address,
        btc_address,
        w3.to_wei(1, 'ether'),
        5,
        3600,
        12
    ))
    
    proposal_id = initial_proposal_count + 1
    proposal = pool.functions.proposals(proposal_id).call()
    voting_deadline = proposal[5]
    print(f"✅ Proposal {proposal_id} created! Voting deadline at block {voting_deadline}")
    print(f"   Requested principal: 1 ETH | Interest: 5% | Duration: 3600 blocks")
    print_balances(w3, pool, accounts)

    # 3. Borrower requests Oracle update
    print("3. Borrower is requesting balance update from the Bitcoin oracle...")
    min_fee = oracle.functions.minFee().call()
    send_tx_with_value(w3, borrower, oracle.functions.requestUpdate(btc_address), min_fee)
    print("✅ Oracle update requested!")
    
    print("\n⏳ Waiting for background services (oracle_service.py and auto_voter.py) to process...")
    print("Make sure they are running in separate terminals!")
    
    # Poll for oracle update and vote
    oracle_deadline = time.monotonic() + 180
    while time.monotonic() < oracle_deadline:
        balance = oracle.functions.getBalance(btc_address).call()
        prop = pool.functions.proposals(proposal_id).call()
        yes_votes = prop[6]
        if balance > 0 and yes_votes > 0:
            print(f"✅ Oracle updated balance: {balance} satoshis")
            print(f"✅ Auto-Voter casted Yes vote with weight: {w3.from_wei(yes_votes, 'ether')} ETH")
            print_balances(w3, pool, accounts)
            break
        time.sleep(5)
        print("   Polling...")
    else:
        print("❌ Oracle/voter did not complete within 180 seconds. Verify both background services and Bitcoin data.")
        return

    # Wait for voting period to end
    print("\n⏳ Waiting for voting period to end (12 blocks)...")
    while True:
        current_block = w3.eth.block_number
        if current_block >= voting_deadline:
            print(f"✅ Voting period ended! Current block: {current_block}")
            break
        print(f"   Current block: {current_block} / {voting_deadline}. Waiting...")
        time.sleep(5)

    # 4. Borrower executes loan
    print("\n4. Borrower is executing the approved loan...")
    receipt = send_tx(w3, borrower, pool.functions.executeApprovedLoan(proposal_id))
    
    # Extract LoanApproved event to get LoanContract address
    loan_address = None
    for log in receipt.logs:
        try:
            event = pool.events.LoanApproved().process_log(log)
            loan_address = event['args']['loanContract']
            break
        except Exception:
            continue
            
    if not loan_address:
        print("❌ Failed to find LoanApproved event. Loan might have been rejected.")
        prop = pool.functions.proposals(proposal_id).call()
        print(f"Executed: {prop[8]}")
        return

    print(f"✅ Loan executed successfully! LoanContract address: {loan_address}")
    print_balances(w3, pool, accounts)

    # 5. Borrower repays the loan
    print("\n5. Borrower is repaying the loan with 5% interest (1.05 ETH)...")
    loan_contract = get_contract(w3, "LoanContract", loan_address)
    send_tx_with_value(w3, borrower, loan_contract.functions.repay(), w3.to_wei(1.05, 'ether'))
    print("✅ Loan repaid successfully!")
    print_balances(w3, pool, accounts)
    
    # 6. Contributor claims interest
    print("\n6. Contributor is claiming interest gains...")
    send_tx(w3, contributor, pool.functions.claimInterestGain())
    print("✅ Interest gain claimed!")
    
    print("\n🎉 Simulation Complete! Final Balances:")
    print_balances(w3, pool, accounts)
    
    comp_pool = w3.from_wei(pool.functions.compensationPoolBalance().call(), 'ether')
    print(f"Compensation Pool Balance: {comp_pool:.4f} ETH")

if __name__ == "__main__":
    main()
