"""
auto_voter.py — Automated voting bot for loan proposals.

Operation:
1. Connects to the local node (Hardhat).
2. Listens for the 'LoanProposed' event emitted by the FundingPool.
3. Evaluates loan parameters using a predefined strategy.
4. Automatically sends the voting transaction (Yes/No).
"""

import json
import logging
import os
import time

from dotenv import load_dotenv
from web3 import Web3
from web3.exceptions import ContractLogicError

load_dotenv(".env")

# ─── Logging Configuration ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── Constants and Parameters ────────────────────────────────────────────────────
RPC_URL = os.getenv("ETH_RPC_URL", "http://127.0.0.1:8545")
POOL_ADDRESS = os.getenv("POOL_ADDRESS")
VOTER_PRIVATE_KEY = os.getenv("VOTER_PRIVATE_KEY")
POLL_INTERVAL = 5 # Seconds between checks

# Dynamic ABI loading from Hardhat's compiled file
# Make sure the path is correct relative to where you run the script
ABI_PATH = os.path.join(
    os.path.dirname(__file__), 
    "../../artifacts/contracts/FundingPool.sol/FundingPool.json"
)

# ─── Voting Function ────────────────────────────────────────────────────────
def evaluate_and_vote(pool_contract, voter_account, w3, proposal_id, principal, interest_bps, duration_blocks):
    """
    Evaluates parameters and sends the voting transaction.
    """
    # 1. Evaluation logic: the trace requires to always vote YES
    support = True
    reason = "Automated strategy (always YES)."
    vote_str = "YES"

    logger.info(f"Evaluation Proposal #{proposal_id}: Vote {vote_str} -> {reason}")

    # 2. Transaction creation and sending
    try:
        nonce = w3.eth.get_transaction_count(voter_account.address)
        
        tx = pool_contract.functions.voteOnProposal(proposal_id, support).build_transaction({
            "from": voter_account.address,
            "nonce": nonce,
            "gas": 200000,
            "gasPrice": w3.eth.gas_price,
        })
        
        signed_tx = voter_account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        logger.info(f"Voting transaction sent! Hash: {tx_hash.hex()}")
        
        # Wait for receipt
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt["status"] == 1:
            logger.info(f"Vote successfully recorded in block {receipt['blockNumber']}!")
        else:
            logger.error("Vote failed. Transaction reverted.")
        
    except ContractLogicError as e:
        logger.error(f"Contract logic error during voting: {e}")
    except Exception as e:
        logger.error(f"Network/Transaction sending error: {e}")


# ─── Polling Loop ────────────────────────────────────────────────────────
def run_polling_loop(pool_contract, voter_account, w3):
    """
    Continuously scans new blocks to intercept the 'LoanProposed' event.
    """
    logger.info("=== AUTO-VOTER STARTED ===")
    logger.info(f"Listening on Pool address: {pool_contract.address}")
    logger.info(f"Voter account: {voter_account.address}")
    
    last_checked_block = w3.eth.block_number
    logger.info(f"Starting from block: {last_checked_block}")

    # We get the event signature (topic) to filter it
    event_signature = w3.keccak(text="LoanProposed(uint256,address,string,uint256,uint256,uint256,uint256)").hex()

    while True:
        time.sleep(POLL_INTERVAL)
        try:
            current_block = w3.eth.block_number

            if current_block <= last_checked_block:
                continue

            # Look for logs between the last checked block and the current one
            logs = w3.eth.get_logs({
                "address": pool_contract.address,
                "topics": [event_signature],
                "fromBlock": last_checked_block + 1,
                "toBlock": current_block,
            })

            last_checked_block = current_block

            for log in logs:
                # Decode the event using web3.py
                event = pool_contract.events.LoanProposed().process_log(log)
                args = event["args"]
                
                proposal_id = args["proposalId"]
                borrower = args["borrower"]
                principal = args["principal"]
                interest_bps = args["interestBps"]
                duration_blocks = args["durationBlocks"]
                
                principal_eth = w3.from_wei(principal, 'ether')
                
                logger.info("--- NEW PROPOSAL DETECTED ---")
                logger.info(f"ID: {proposal_id} | Da: {borrower}")
                logger.info(f"Request: {principal_eth} ETH | Interest: {interest_bps} bps | Duration: {duration_blocks} blocks")
                
                evaluate_and_vote(pool_contract, voter_account, w3, proposal_id, principal, interest_bps, duration_blocks)

        except Exception as e:
            logger.error(f"Polling loop error: {e}. Retrying in {POLL_INTERVAL} seconds...")


# ─── Entry Point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    
    if not w3.is_connected():
        logger.error("Failed to connect to Ethereum node. Ensure Hardhat or Geth is running.")
        exit(1)
        
    if POOL_ADDRESS == "0x..." or VOTER_PRIVATE_KEY == "0x...":
        logger.error("You must configure POOL_ADDRESS and VOTER_PRIVATE_KEY in the script or in the .env file!")
        exit(1)

    voter_account = w3.eth.account.from_key(VOTER_PRIVATE_KEY)
    
    with open(ABI_PATH) as f:
        pool_abi = json.load(f)["abi"]

    pool_contract = w3.eth.contract(
        address=Web3.to_checksum_address(POOL_ADDRESS),
        abi=pool_abi
    )

    run_polling_loop(pool_contract, voter_account, w3)