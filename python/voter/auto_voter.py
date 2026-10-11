"""Always-YES contributor bot, with a persistent event inbox and retry outbox."""

import json
import logging
import os
from pathlib import Path
import sys
import time

from dotenv import load_dotenv
from web3 import Web3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from durable_events import (
    EventStore, PermanentEventError, make_web3, process_pending, require_local_chain,
    scan_events, send_durable, store_identity,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)
POLL_INTERVAL = 5
SIGNATURE = "LoanProposed(uint256,address,string,uint256,uint256,uint256,uint256)"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ABI_PATH = PROJECT_ROOT / "artifacts/contracts/FundingPool.sol/FundingPool.json"


def evaluate_and_vote(pool_contract, voter_account, w3, proposal_id, store, event_id):
    if pool_contract.functions.hasVoted(proposal_id, voter_account.address).call():
        if not pool_contract.functions.voteSupport(proposal_id, voter_account.address).call():
            raise PermanentEventError(f"Proposal {proposal_id} already has a NO from this account; votes cannot be changed")
        logger.info("Proposal %s already has this contributor's vote", proposal_id)
        return
    proposal = pool_contract.functions.proposals(proposal_id).call()
    if proposal[8] or pool_contract.functions.terminated().call():
        raise PermanentEventError(f"Proposal {proposal_id} or the service is already closed; vote missed")
    # Contributors with fully locked funds still cast a YES with zero current
    # weight. The contract recomputes the weight when the applicant resolves.
    if pool_contract.functions.totalContributed(voter_account.address).call() == 0:
        raise RuntimeError("Voter has no pool contribution yet; fund its position and retry")
    receipt = send_durable(
        w3, voter_account, pool_contract.functions.voteOnProposal(proposal_id, True), store, event_id,
    )
    if not pool_contract.functions.hasVoted(proposal_id, voter_account.address).call():
        raise RuntimeError("Successful receipt did not record the expected vote")
    logger.info("YES recorded for proposal %s in block %s", proposal_id, receipt["blockNumber"])


def run_polling_loop(pool_contract, voter_account, w3, store):
    logger.info("AUTO-VOTER: pool=%s voter=%s next block=%s", pool_contract.address, voter_account.address, store.next_block)
    while True:
        try:
            scan_events(w3, pool_contract, "LoanProposed", SIGNATURE, store)
            process_pending(store, lambda event_id, args: evaluate_and_vote(
                pool_contract, voter_account, w3, args["proposalId"], store, event_id,
            ), logger)
        except Exception as exc:
            logger.error("Polling error; stored cursor/events retained: %s", exc)
        time.sleep(POLL_INTERVAL)


def main():
    load_dotenv(Path(__file__).with_name(".env"))
    w3 = make_web3(os.getenv("ETH_RPC_URL", "http://127.0.0.1:8545"))
    require_local_chain(w3)
    pool_address = os.environ["POOL_ADDRESS"]
    voter_account = w3.eth.account.from_key(os.environ["VOTER_PRIVATE_KEY"])
    with ABI_PATH.open() as stream:
        abi = json.load(stream)["abi"]
    pool_contract = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=abi)
    if not w3.eth.get_code(pool_contract.address):
        raise RuntimeError("POOL_ADDRESS has no contract code on this chain; run setup first")
    database = os.getenv("EVENT_DB_PATH", str(Path(__file__).with_name(
        f"events-{pool_address.lower()}-{voter_account.address.lower()}.sqlite3")))
    store = EventStore(database, store_identity(w3, pool_address, voter_account.address),
                       int(os.getenv("DEPLOYMENT_BLOCK", "0")))
    try:
        run_polling_loop(pool_contract, voter_account, w3, store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
