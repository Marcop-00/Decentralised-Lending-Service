"""Exercise the real oracle and voting services on the course's local chain."""

import argparse
import json
import os
from pathlib import Path
import time

from dotenv import load_dotenv
from web3 import Web3
from web3.logs import DISCARD

from durable_events import checked_receipt, make_web3, require_local_chain

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_contract(w3, contract_name, address):
    artifact_path = PROJECT_ROOT / f"artifacts/contracts/{contract_name}.sol/{contract_name}.json"
    artifact = json.loads(artifact_path.read_text())
    address = Web3.to_checksum_address(address)
    if not w3.eth.get_code(address):
        raise RuntimeError(f"{contract_name} has no code at {address}")
    return w3.eth.contract(address=address, abi=artifact["abi"])


def send_tx_with_value(w3, account, tx_call, value=0):
    transaction = tx_call.build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, "pending"),
        "value": value, "gasPrice": w3.eth.gas_price, "chainId": 202526,
    })
    signed = account.sign_transaction(transaction)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return checked_receipt(w3.eth.wait_for_transaction_receipt(tx_hash))


def send_tx(w3, account, tx_call):
    return send_tx_with_value(w3, account, tx_call)


def required_satoshis(principal_wei):
    denominator = 30 * 10**18
    return (principal_wei * 100_000_000 + denominator - 1) // denominator


def event_position(event):
    return (int(event["blockNumber"]), int(event["transactionIndex"]), int(event["logIndex"]))


def single_event(event_type, receipt):
    events = event_type.process_receipt(receipt, errors=DISCARD)
    if len(events) != 1:
        raise RuntimeError(f"Expected one {event_type.event_name} event, found {len(events)}")
    return events[0]


def wait_until(predicate, timeout, description):
    expires = time.monotonic() + timeout
    while time.monotonic() < expires:
        result = predicate()
        if result:
            return result
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {description}; check both services and their persistent queue logs")


def wait_for_fresh_balance(w3, oracle, request_event, btc_address, timeout):
    def fresh_balance():
        events = oracle.events.BalanceUpdated().get_logs(
            from_block=request_event["blockNumber"], to_block=w3.eth.block_number,
        )
        matching = [event for event in events
                    if event["args"]["btcAddress"] == btc_address
                    and event_position(event) > event_position(request_event)]
        # A zero balance is also a valid response. Return the event, not its
        # numeric balance, so zero doesn't masquerade as an unserved request.
        return max(matching, key=event_position) if matching else None
    event = wait_until(fresh_balance, timeout, "a new BalanceUpdated event after this request")
    return int(event["args"]["balanceInSatoshi"])


def print_balances(w3, pool, accounts):
    print("\n--- Balances and protocol state ---")
    for name, account in accounts.items():
        wallet = w3.from_wei(w3.eth.get_balance(account.address), "ether")
        print(f"{name}: {wallet} ETH")
        if name == "Contributor":
            for label, function in (("Disposable", pool.functions.unlockedBalanceOf),
                                    ("Locked", pool.functions.lockedContributions),
                                    ("Unclaimed gain", pool.functions.pendingInterestGain)):
                print(f"  {label}: {w3.from_wei(function(account.address).call(), 'ether')} ETH")
    print(f"Pool ETH balance: {w3.from_wei(w3.eth.get_balance(pool.address), 'ether')}")
    print(f"Disposable: {pool.functions.totalUnlockedFunds().call()} wei")
    print(f"Compensation: {pool.functions.compensationPoolBalance().call()} wei")
    print(f"Collateral: {pool.functions.collateralPercentage().call()}%; active loans: {pool.functions.activeLoanCount().call()}")


def main():
    load_dotenv(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--btc-address", default=os.getenv("BTC_ADDRESS"),
                        help="Bitcoin address with enough actual UTXOs in the first 131,000 blocks")
    parser.add_argument("--principal", default="1", help="Loan principal in ETH (default: 1)")
    parser.add_argument("--timeout", type=int, default=300, help="Maximum seconds per asynchronous step")
    args = parser.parse_args()
    if not args.btc_address:
        parser.error("Set BTC_ADDRESS or pass --btc-address from your complete Bitcoin dataset")
    principal = Web3.to_wei(args.principal, "ether")
    if principal <= 0 or args.timeout <= 0:
        parser.error("Principal and timeout must be positive")

    w3 = make_web3(os.getenv("ETH_RPC_URL", "http://127.0.0.1:8545"))
    require_local_chain(w3)
    pool = get_contract(w3, "FundingPool", os.environ["POOL_ADDRESS"])
    oracle = get_contract(w3, "BitcoinOracle", os.environ["ORACLE_ADDRESS"])
    operator = w3.eth.account.from_key(os.environ["OPERATOR_PRIVATE_KEY"])
    contributor = w3.eth.account.from_key(os.environ["VOTER_PRIVATE_KEY"])
    borrower = w3.eth.account.from_key(os.environ["BORROWER_PRIVATE_KEY"])
    accounts = {"Deployer": operator, "Contributor": contributor, "Borrower": borrower}
    print("Keep oracle_service.py and auto_voter.py running; wait for ORACLE READY before starting this demonstration.")
    print_balances(w3, pool, accounts)

    print("1. Requesting fresh Bitcoin liquidity from the running oracle...")
    receipt = send_tx_with_value(w3, borrower, oracle.functions.requestUpdate(args.btc_address),
                                 oracle.functions.minFee().call())
    request_event = single_event(oracle.events.UpdateRequested(), receipt)
    print_balances(w3, pool, accounts)
    sats = wait_for_fresh_balance(w3, oracle, request_event, args.btc_address, args.timeout)
    required = required_satoshis(principal)
    if sats < required:
        raise RuntimeError(f"Actual Bitcoin balance {sats} satoshi is below the required {required}; choose a funded address or an explicitly smaller --principal")
    print(f"Fresh oracle balance: {sats} satoshi; required: {required} satoshi")
    print_balances(w3, pool, accounts)

    print("2. Funding the contributor's pool position...")
    disposable = pool.functions.unlockedBalanceOf(contributor.address).call()
    target = max(w3.to_wei(50, "ether"), principal * 2)
    if disposable < target:
        deposit = max(target - disposable, pool.functions.MIN_DEPOSIT_WEI().call() + 1)
        send_tx_with_value(w3, contributor, pool.functions.contribute(), deposit)
    print_balances(w3, pool, accounts)

    print("3. Creating a loan proposal...")
    receipt = send_tx(w3, borrower, pool.functions.createLoanProposal(
        borrower.address, args.btc_address, principal, 5, 3600, 12,
    ))
    proposed = single_event(pool.events.LoanProposed(), receipt)
    proposal_id = proposed["args"]["proposalId"]
    resolution_block = proposed["args"]["votingDeadlineBlock"]
    print(f"Proposal {proposal_id}; earliest resolution block {resolution_block}")
    print_balances(w3, pool, accounts)

    wait_until(lambda: pool.functions.hasVoted(proposal_id, contributor.address).call(),
               args.timeout, "the configured contributor's vote")
    if not pool.functions.voteSupport(proposal_id, contributor.address).call():
        raise RuntimeError("The configured contributor recorded NO instead of the required YES")
    print("4. The actual configured contributor has voted YES.")
    print_balances(w3, pool, accounts)
    wait_until(lambda: w3.eth.block_number >= resolution_block, args.timeout, "12 voting blocks")
    receipt = send_tx(w3, borrower, pool.functions.executeApprovedLoan(proposal_id))
    approved = pool.events.LoanApproved().process_receipt(receipt, errors=DISCARD)
    if not approved:
        rejected = pool.events.LoanRejected().process_receipt(receipt, errors=DISCARD)
        reason = rejected[0]["args"]["reason"] if rejected else "no approval event"
        raise RuntimeError(f"Proposal closed without a loan: {reason}")
    loan = get_contract(w3, "LoanContract", approved[0]["args"]["loanContract"])
    print(f"5. Loan created at {loan.address}; actual principal={loan.functions.principal().call()} wei")
    print_balances(w3, pool, accounts)

    due = loan.functions.dueAmount().call()
    installment = due // 2
    if installment:
        send_tx_with_value(w3, borrower, loan.functions.repay(), installment)
        print(f"6. First installment: {installment} wei")
        print_balances(w3, pool, accounts)
    send_tx_with_value(w3, borrower, loan.functions.repay(), due - installment)
    print(f"7. Final installment; loan status={loan.functions.status().call()}")
    print_balances(w3, pool, accounts)

    gain = pool.functions.pendingInterestGain(contributor.address).call()
    if gain:
        send_tx(w3, contributor, pool.functions.claimInterestGain())
        print("8. Contributor claimed the accrued interest.")
        print_balances(w3, pool, accounts)
    print("Demonstration complete.")


if __name__ == "__main__":
    main()
