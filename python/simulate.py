"""Demonstrate repayment, default and compensation using the real local services."""

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


def verify_state(description, checks):
    failed = [name for name, correct in checks.items() if not correct]
    if failed:
        raise RuntimeError(f"{description}: unexpected state: {', '.join(failed)}")


def create_demo_loan(w3, pool, accounts, btc_address, principal, *, rate, duration, timeout):
    borrower, contributor = accounts["Borrower"], accounts["Contributor"]
    receipt = send_tx(w3, borrower, pool.functions.createLoanProposal(
        borrower.address, btc_address, principal, rate, duration, 12,
    ))
    proposed = single_event(pool.events.LoanProposed(), receipt)
    proposal_id = proposed["args"]["proposalId"]
    resolution_block = proposed["args"]["votingDeadlineBlock"]
    print_rows("PROPOSAL CREATED", (
        ("Proposal ID", proposal_id),
        ("Requested principal", format_eth(principal)),
        ("Interest rate", f"{rate}%"),
        ("Duration", f"{duration:,} blocks"),
        ("Earliest resolution block", f"{resolution_block:,}"),
    ))
    print_balances(w3, pool, accounts)

    print("\nWaiting for the automatic contributor vote...", flush=True)
    wait_until(lambda: pool.functions.hasVoted(proposal_id, contributor.address).call(),
               timeout, "the configured contributor's vote")
    if not pool.functions.voteSupport(proposal_id, contributor.address).call():
        raise RuntimeError("The configured contributor recorded NO instead of the required YES")
    print("[OK] The configured contributor voted YES.")
    print_balances(w3, pool, accounts)
    print(f"\nWaiting for the voting period: resolution from block {resolution_block:,}...", flush=True)
    wait_until(lambda: w3.eth.block_number >= resolution_block, timeout, "12 voting blocks")
    receipt = send_tx(w3, borrower, pool.functions.executeApprovedLoan(proposal_id))
    approved = pool.events.LoanApproved().process_receipt(receipt, errors=DISCARD)
    if len(approved) != 1:
        rejected = pool.events.LoanRejected().process_receipt(receipt, errors=DISCARD)
        reason = rejected[0]["args"]["reason"] if rejected else "no unique approval event"
        raise RuntimeError(f"Proposal closed without a loan: {reason}")
    loan = get_contract(w3, "LoanContract", approved[0]["args"]["loanContract"])
    print(f"\n[OK] Loan approved and funded. Contract: {loan.address}")
    print_balances(w3, pool, accounts)
    print_loan_state(w3, pool, loan, proposal_id, contributor)
    return proposal_id, loan


def print_loan_state(w3, pool, loan, proposal_id, contributor):
    status_names = ("Created", "Funded", "Repaid", "Defaulted")
    status = int(loan.functions.status().call())
    print_rows(f"LOAN {proposal_id} | {status_names[status]}", (
        ("Current block", f"{w3.eth.block_number:,}"),
        ("Due block (inclusive)", f"{loan.functions.dueBlock().call():,}"),
        ("Actual principal", format_eth(loan.functions.principal().call())),
        ("Fixed collateral", f"{loan.functions.collateralPercentage().call()}%"),
        ("Repaid principal", format_eth(loan.functions.repaidPrincipal().call())),
        ("Repaid interest", format_eth(loan.functions.repaidInterest().call())),
        ("Contributor's remaining principal claim",
         format_eth(pool.functions.loanContributions(proposal_id, contributor.address).call())),
    ))


def wait_for_expiry(w3, loan, timeout):
    due_block = loan.functions.dueBlock().call()
    wait_until(lambda: w3.eth.block_number > due_block, timeout,
               f"loan expiry (a block strictly greater than {due_block})")


def compensation_state(w3, pool, loan, proposal_id, contributor):
    return {
        "owed": pool.functions.loanContributions(proposal_id, contributor.address).call(),
        "locked": pool.functions.lockedContributions(contributor.address).call(),
        "contributed": pool.functions.totalContributed(contributor.address).call(),
        "disposable": pool.functions.unlockedBalanceOf(contributor.address).call(),
        "pool_disposable": pool.functions.totalUnlockedFunds().call(),
        "reserve": pool.functions.compensationPoolBalance().call(),
        "failed_count": pool.functions.failedLoanCount().call(),
        "collateral": pool.functions.collateralPercentage().call(),
        "active": pool.functions.activeLoanCount().call(),
        "failed": pool.functions.isLoanFailed(proposal_id).call(),
        "resolved": pool.functions.loanResolved(loan.address).call(),
        "status": loan.functions.status().call(),
        "cash": w3.eth.get_balance(pool.address),
    }


def claim_demo_compensation(w3, pool, loan, proposal_id, contributor):
    before = compensation_state(w3, pool, loan, proposal_id, contributor)
    receipt = send_tx(w3, contributor, pool.functions.requestCompensation(loan.address))
    event = single_event(pool.events.CompensationRequested(), receipt)
    paid = int(event["args"]["amount"])
    after = compensation_state(w3, pool, loan, proposal_id, contributor)
    verify_state("Compensation", {
        "event recipient": event["args"]["contributor"].lower() == contributor.address.lower(),
        "paid amount": paid == min(before["owed"], before["reserve"]),
        "remaining claim": after["owed"] == before["owed"] - paid,
        "locked principal": after["locked"] == before["locked"] - paid,
        "total contribution": after["contributed"] == before["contributed"] - paid,
        "disposable unchanged": after["disposable"] == before["disposable"],
        "pool disposable unchanged": after["pool_disposable"] == before["pool_disposable"],
        "reserve": after["reserve"] == before["reserve"] - paid,
        "pool ETH": after["cash"] == before["cash"] - paid,
        "irreversible default": after["status"] == 3 and after["failed"],
        "resolved loan": after["resolved"],
        "failure counted once": after["failed_count"] == before["failed_count"] + (not before["failed"]),
        "collateral adjusted once": after["collateral"] == (before["collateral"] if before["failed"] else min(100, before["collateral"] + 5)),
        "active loan count": after["active"] == before["active"] - (not before["resolved"]),
    })
    print_rows("COMPENSATION RESULT | accounting checks passed", (
        ("Paid to contributor wallet", format_eth(paid)),
        ("Uncovered principal claim", format_eth(after["owed"])),
    ))
    print("  The uncovered claim is not withdrawable ETH; future recovery is not guaranteed.")
    return paid


def print_balances(w3, pool, accounts):
    print("\n" + "-" * 72)
    print("STATE OVERVIEW")
    print_rows("WALLETS AND CONTRACT BALANCES", (
        *((f"{name} wallet", format_eth(w3.eth.get_balance(account.address)))
          for name, account in accounts.items()),
        ("FundingPool contract", format_eth(w3.eth.get_balance(pool.address))),
        ("BitcoinOracle contract", format_eth(w3.eth.get_balance(pool.functions.bitcoinOracle().call()))),
    ))
    if "Contributor" in accounts:
        contributor = accounts["Contributor"].address
        print_rows("CONTRIBUTOR POSITION | accounted in the pool, not in the wallet", (
            ("Total contribution", format_eth(pool.functions.totalContributed(contributor).call())),
            ("Disposable capital", format_eth(pool.functions.unlockedBalanceOf(contributor).call())),
            ("Locked principal", format_eth(pool.functions.lockedContributions(contributor).call())),
            ("Interest gain to claim", format_eth(pool.functions.pendingInterestGain(contributor).call())),
        ))
    print_rows("POOL ACCOUNTING AND PROTOCOL", (
        ("Disposable capital", format_eth(pool.functions.totalUnlockedFunds().call())),
        ("Compensation reserve", format_eth(pool.functions.compensationPoolBalance().call())),
        ("Global collateral", f"{pool.functions.collateralPercentage().call()}%"),
        ("Active loans", pool.functions.activeLoanCount().call()),
        ("Failed loans", pool.functions.failedLoanCount().call()),
    ))


def format_units(amount, decimals):
    """Format integer base units exactly; never round balances through floats."""
    sign = "-" if amount < 0 else ""
    whole, remainder = divmod(abs(amount), 10**decimals)
    fraction = f"{remainder:0{decimals}d}".rstrip("0")
    return f"{sign}{whole:,}" + (f".{fraction}" if fraction else "")


def format_eth(wei):
    return f"{format_units(wei, 18)} ETH"


def print_rows(title, rows):
    rows = tuple(rows)
    width = max((len(label) for label, _ in rows), default=0)
    print(f"\n{title}")
    for label, value in rows:
        print(f"  {label:<{width}} : {value}")


def print_step(number, title):
    print("\n" + "=" * 72)
    print(f"STEP {number}/10 | {title}")
    print("=" * 72, flush=True)


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
    print("\n" + "=" * 72)
    print("DECENTRALISED LENDING SERVICE | DEMONSTRATION")
    print("=" * 72)
    print("Keep oracle_service.py and auto_voter.py running.")
    print("Start only after the oracle has printed ORACLE READY.")
    print("Wallet balances and pool positions are shown separately.")
    print("Step numbers identify demo phases, not transaction counts.")
    print_rows("DEMO SETTINGS", (
        ("Bitcoin address", args.btc_address),
        ("Scenario A principal", format_eth(principal)),
        ("Scenario B principal", format_eth(max(1, principal // 2))),
        ("Timeout per waiting phase", f"{args.timeout} seconds"),
    ))
    print_balances(w3, pool, accounts)

    print_step(1, "REQUEST BITCOIN LIQUIDITY")
    receipt = send_tx_with_value(w3, borrower, oracle.functions.requestUpdate(args.btc_address),
                                 oracle.functions.minFee().call())
    request_event = single_event(oracle.events.UpdateRequested(), receipt)
    print_balances(w3, pool, accounts)
    print("\nWaiting for a fresh response from the running oracle...", flush=True)
    sats = wait_for_fresh_balance(w3, oracle, request_event, args.btc_address, args.timeout)
    required = required_satoshis(principal)
    if sats < required:
        raise RuntimeError(f"Actual Bitcoin balance {sats} satoshi is below the required {required}; choose a funded address or an explicitly smaller --principal")
    print_rows("ORACLE RESPONSE | liquidity check passed", (
        ("Actual Bitcoin balance", f"{sats:,} satoshi ({format_units(sats, 8)} BTC)"),
        ("Required Bitcoin balance", f"{required:,} satoshi"),
    ))
    print_balances(w3, pool, accounts)

    print_step(2, "FUND THE CONTRIBUTOR'S POOL POSITION")
    disposable = pool.functions.unlockedBalanceOf(contributor.address).call()
    target = max(w3.to_wei(50, "ether"), principal * 2)
    if disposable < target:
        deposit = max(target - disposable, pool.functions.MIN_DEPOSIT_WEI().call() + 1)
        send_tx_with_value(w3, contributor, pool.functions.contribute(), deposit)
        print(f"[OK] Deposited {format_eth(deposit)} into the pool.")
    else:
        print("No deposit needed: the contributor already has enough disposable capital.")
    print_balances(w3, pool, accounts)

    print_step(3, "SCENARIO A | CREATE AND FUND THE FIRST LOAN")
    proposal_id, loan = create_demo_loan(
        w3, pool, accounts, args.btc_address, principal,
        rate=5, duration=3600, timeout=args.timeout,
    )

    due = loan.functions.dueAmount().call()
    installment = due // 2
    print_step(4, "SCENARIO A | FIRST INSTALLMENT")
    if installment:
        send_tx_with_value(w3, borrower, loan.functions.repay(), installment)
        print(f"[OK] Borrower paid {format_eth(installment)}.")
        print_balances(w3, pool, accounts)
        print_loan_state(w3, pool, loan, proposal_id, contributor)
    else:
        print("Skipped: the full debt will be settled by the final installment.")
    print_step(5, "SCENARIO A | FINAL INSTALLMENT")
    send_tx_with_value(w3, borrower, loan.functions.repay(), due - installment)
    verify_state("Successful repayment", {"loan closed as Repaid": loan.functions.status().call() == 2})
    print(f"[OK] Borrower paid {format_eth(due - installment)}. Loan status: Repaid.")
    print_balances(w3, pool, accounts)
    print_loan_state(w3, pool, loan, proposal_id, contributor)

    gain = pool.functions.pendingInterestGain(contributor.address).call()
    print_step(6, "SCENARIO A | CLAIM CONTRIBUTOR INTEREST")
    if gain:
        send_tx(w3, contributor, pool.functions.claimInterestGain())
        print(f"[OK] Claimed {format_eth(gain)} into the contributor wallet.")
        print_balances(w3, pool, accounts)
    else:
        print("No accrued interest to claim.")

    print_step(7, "SCENARIO B | CREATE A LOAN THAT WILL NOT BE REPAID")
    failed_id, failed_loan = create_demo_loan(
        w3, pool, accounts, args.btc_address, max(1, principal // 2),
        rate=10, duration=3, timeout=args.timeout,
    )
    print_step(8, "SCENARIO B | WAIT UNTIL THE LOAN IS OVERDUE")
    print("Waiting for real chain blocks beyond the due block...", flush=True)
    wait_for_expiry(w3, failed_loan, args.timeout)
    print("The deadline has passed. Storage changes only when a transaction records the default.")
    print_balances(w3, pool, accounts)
    print_loan_state(w3, pool, failed_loan, failed_id, contributor)

    print_step(9, "SCENARIO B | RECORD DEFAULT AND REQUEST COMPENSATION")
    claim_demo_compensation(w3, pool, failed_loan, failed_id, contributor)
    print_balances(w3, pool, accounts)
    print_loan_state(w3, pool, failed_loan, failed_id, contributor)
    if pool.functions.loanContributions(failed_id, contributor.address).call() > 0:
        print_step(10, "SCENARIO B | RETRY THE REMAINING COMPENSATION CLAIM")
        print("An empty reserve pays zero; the remaining claim is preserved.")
        claim_demo_compensation(w3, pool, failed_loan, failed_id, contributor)
        print_balances(w3, pool, accounts)
        print_loan_state(w3, pool, failed_loan, failed_id, contributor)
    else:
        print_step(10, "SCENARIO B | NO REMAINING COMPENSATION CLAIM")
        print("No retry needed: the contributor's principal claim has been fully covered.")
    print("The failed loan stays Defaulted. Remaining locked capital is a loss claim, not disposable ETH.")
    print("\n" + "=" * 72)
    print("DEMONSTRATION COMPLETE | repayment, default and compensation checked")
    print("=" * 72)


if __name__ == "__main__":
    main()
