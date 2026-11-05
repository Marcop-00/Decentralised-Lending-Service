import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { getAddress, parseEventLogs, type Abi, type Address, type TransactionReceipt } from "viem";
import { deployProtocol, parseEther } from "./helpers/deployProtocol.ts";

type EventSource = { address: Address; abi: Abi };

// Decode this transaction's logs only, including the emitter: calls through
// delegatecall must emit pool events from the proxy, not the implementation.
function events(receipt: TransactionReceipt, source: EventSource, eventName: string) {
  return parseEventLogs({
    abi: source.abi,
    eventName,
    logs: receipt.logs.filter((log) => log.address.toLowerCase() === source.address.toLowerCase()),
    strict: true,
  });
}

function expectEvent(receipt: TransactionReceipt, source: EventSource, eventName: string, args: Record<string, unknown> | undefined) {
  const logs = events(receipt, source, eventName);
  assert.equal(logs.length, 1, `Expected exactly one ${eventName} from ${source.address}`);
  assert.deepEqual(logs[0].args, args, `Incorrect ${eventName} arguments`);
}

describe("Section 1.5: events and dedicated loan contracts", () => {
  it("emits lifecycle events once, from the correct contract, with the expected arguments", async () => {
    const f = await deployProtocol();
    const contributor = getAddress(f.contributor.account.address);
    const borrower = getAddress(f.borrower.account.address);
    const btcAddress = "1EventLiquidityAddress";
    const deposit = parseEther("10");
    let receipt = await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: deposit }));
    expectEvent(receipt, f.pool, "ContributionAdded", { contributor, amount: deposit });

    const fee = await f.oracle.read.minFee();
    receipt = await f.receipt(await f.oracle.write.requestUpdate([btcAddress], { account: f.borrower.account, value: fee }));
    expectEvent(receipt, f.oracle, "UpdateRequested", { btcAddress, requester: borrower, fee });
    receipt = await f.receipt(await f.oracle.write.update([btcAddress, 100_000_000n]));
    expectEvent(receipt, f.oracle, "BalanceUpdated", { btcAddress, balanceInSatoshi: 100_000_000n });

    const principal = parseEther("2");
    receipt = await f.receipt(await f.pool.write.createLoanProposal([
      borrower, btcAddress, principal, 10n, 1000n, 12n,
    ], { account: f.borrower.account }));
    const id = await f.pool.read.proposalCount();
    expectEvent(receipt, f.pool, "LoanProposed", {
      proposalId: id, borrower, borrowerBtcAddress: btcAddress,
      principal, interestRate: 10n, durationBlocks: 1000n,
      votingDeadlineBlock: receipt.blockNumber + 12n,
    });
    receipt = await f.receipt(await f.pool.write.voteOnProposal([id, true], { account: f.contributor.account }));
    expectEvent(receipt, f.pool, "VoteCast", { proposalId: id, voter: contributor, support: true, weight: deposit });
    await f.networkHelpers.mine(12);
    receipt = await f.receipt(await f.pool.write.executeApprovedLoan([id], { account: f.borrower.account }));
    const loan = await f.loanFor(id);
    expectEvent(receipt, f.pool, "FundsLocked", { contributor, amount: principal });
    expectEvent(receipt, f.pool, "LoanApproved", { proposalId: id, loanContract: getAddress(loan.address) });
    assert.equal(events(receipt, f.pool, "LoanRejected").length, 0);

    for (let installment = 0; installment < 2; installment++) {
      receipt = await f.receipt(await loan.write.repay({ account: f.borrower.account, value: parseEther("1.1") }));
      expectEvent(receipt, loan, "Repayment", {
        principalAmount: parseEther("1"), interestAmount: parseEther("0.1"), excessAmount: 0n,
      });
      expectEvent(receipt, f.pool, "FundsUnlocked", { contributor, amount: parseEther("1") });
      expectEvent(receipt, f.pool, "CompensationPoolFunded", { amount: parseEther("0.05"), collateralPercentage: 50n });
    }
    receipt = await f.receipt(await f.pool.write.claimInterestGain({ account: f.contributor.account }));
    expectEvent(receipt, f.pool, "InterestClaimed", { contributor, amount: parseEther("0.1") });
    receipt = await f.receipt(await f.pool.write.withdraw([parseEther("1")], { account: f.contributor.account }));
    expectEvent(receipt, f.pool, "ContributionWithdrawn", { contributor, amount: parseEther("1") });

    const rejectedId = await f.createProposal(parseEther("1"), { btcAddress });
    receipt = await f.receipt(await f.pool.write.voteOnProposal([rejectedId, false], { account: f.contributor.account }));
    expectEvent(receipt, f.pool, "VoteCast", {
      proposalId: rejectedId, voter: contributor, support: false, weight: parseEther("9"),
    });
    await f.networkHelpers.mine(12);
    receipt = await f.receipt(await f.pool.write.executeApprovedLoan([rejectedId], { account: f.borrower.account }));
    expectEvent(receipt, f.pool, "LoanRejected", { proposalId: rejectedId, reason: "Majority Reject" });
    assert.equal(events(receipt, f.pool, "LoanApproved").length, 0);

    const failed = await f.approveLoan(parseEther("1"), { duration: 2n });
    await f.networkHelpers.mine(3);
    receipt = await f.receipt(await f.pool.write.requestCompensation([failed.loan.address], { account: f.contributor.account }));
    expectEvent(receipt, failed.loan, "Defaulted", { dueBlock: await failed.loan.read.dueBlock() });
    expectEvent(receipt, f.pool, "LoanDefaulted", { proposalId: failed.id, loanContract: getAddress(failed.loan.address) });
    expectEvent(receipt, f.pool, "CompensationRequested", { contributor, amount: parseEther("0.1") });
    receipt = await f.receipt(await f.pool.write.requestCompensation([failed.loan.address], { account: f.contributor.account }));
    expectEvent(receipt, f.pool, "CompensationRequested", { contributor, amount: 0n });
    assert.equal(events(receipt, f.pool, "LoanDefaulted").length, 0, "A retry must not emit a second default");
    assert.equal(events(receipt, failed.loan, "Defaulted").length, 0);
    receipt = await f.receipt(await f.pool.write.terminate());
    expectEvent(receipt, f.pool, "Terminated", undefined);
  });

  it("deploys distinct loan contracts and isolates terms, borrowers, repayments and positions", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("10") }));
    const first = await f.approveLoan(parseEther("2"), { rate: 10n, duration: 1000n });

    // Use another borrower and different terms, not just another proposal ID.
    const secondBorrower = f.smallContributor.account;
    const btcAddress = "1SecondLoanLiquidityAddress";
    await f.receipt(await f.pool.write.createLoanProposal([
      secondBorrower.address, btcAddress, parseEther("3"), 20n, 2000n, 12n,
    ], { account: secondBorrower }));
    const secondId = await f.pool.read.proposalCount();
    await f.receipt(await f.pool.write.voteOnProposal([secondId, true], { account: f.contributor.account }));
    await f.updateOracle(btcAddress);
    await f.networkHelpers.mine(12);
    const approval = await f.receipt(await f.pool.write.executeApprovedLoan([secondId], { account: secondBorrower }));
    const second = { id: secondId, loan: await f.loanFor(secondId) };

    assert.notEqual(first.loan.address.toLowerCase(), second.loan.address.toLowerCase());
    for (const { id, loan } of [first, second]) {
      const bytecode = await f.publicClient.getBytecode({ address: loan.address });
      assert.ok(bytecode && bytecode !== "0x", "Each loan address must have deployed code");
      assert.notEqual(loan.address.toLowerCase(), f.pool.address.toLowerCase());
      assert.notEqual(loan.address.toLowerCase(), f.implementation.address.toLowerCase());
      assert.equal((await loan.read.pool()).toLowerCase(), f.pool.address.toLowerCase());
      assert.equal(await f.pool.read.loanToProposalId([loan.address]), id);
      assert.equal(await f.pool.read.authorizedLoanContracts([loan.address]), true);
    }
    assert.equal((await first.loan.read.borrower()).toLowerCase(), f.borrower.account.address.toLowerCase());
    assert.equal((await second.loan.read.borrower()).toLowerCase(), secondBorrower.address.toLowerCase());
    assert.equal(await first.loan.read.principal(), parseEther("2"));
    assert.equal(await second.loan.read.principal(), parseEther("3"));
    assert.equal(await first.loan.read.interestRate(), 10n);
    assert.equal(await second.loan.read.interestRate(), 20n);
    assert.equal(await second.loan.read.dueBlock(), approval.blockNumber + 2000n);
    assert.equal(await f.pool.read.activeLoanCount(), 2n);
    assert.equal(await f.pool.read.lockedContributions([f.contributor.account.address]), parseEther("5"));

    async function snapshot({ id, loan }: typeof first) {
      return {
        borrower: await loan.read.borrower(), pool: await loan.read.pool(),
        principal: await loan.read.principal(), rate: await loan.read.interestRate(),
        dueBlock: await loan.read.dueBlock(), collateral: await loan.read.collateralPercentage(),
        status: await loan.read.status(), repaidPrincipal: await loan.read.repaidPrincipal(),
        repaidInterest: await loan.read.repaidInterest(),
        position: await f.pool.read.loanContributions([id, f.contributor.account.address]),
        initialPosition: await f.pool.read.initialLoanContributions([id, f.contributor.account.address]),
        resolved: await f.pool.read.loanResolved([loan.address]), failed: await f.pool.read.isLoanFailed([id]),
      };
    }

    const secondBefore = await snapshot(second);
    for (let installment = 0; installment < 2; installment++) {
      await f.receipt(await first.loan.write.repay({ account: f.borrower.account, value: parseEther("1.1") }));
      assert.deepEqual(await snapshot(second), secondBefore, "Repaying the first loan must not change the second");
    }
    assert.equal(await first.loan.read.status(), 2);
    assert.equal(await f.pool.read.activeLoanCount(), 1n);
    assert.equal(await f.pool.read.collateralPercentage(), 45n);
    assert.equal(await second.loan.read.collateralPercentage(), 50n, "Existing loan terms must not follow global collateral changes");
    assert.equal(await f.pool.read.lockedContributions([f.contributor.account.address]), parseEther("3"));

    // The first borrower is not allowed to repay the other borrower's loan.
    await f.viem.assertions.revertWithCustomError(
      second.loan.write.repay({ account: f.borrower.account, value: 1n }), second.loan, "Unauthorized",
    );
    assert.deepEqual(await snapshot(second), secondBefore);
    const firstClosed = await snapshot(first);
    for (let installment = 0; installment < 2; installment++) {
      await f.receipt(await second.loan.write.repay({ account: secondBorrower, value: parseEther("1.8") }));
      assert.deepEqual(await snapshot(first), firstClosed, "Repaying the second loan must not change the first");
    }
    assert.equal(await second.loan.read.status(), 2);
    assert.equal(await second.loan.read.repaidPrincipal(), parseEther("3"));
    assert.equal(await second.loan.read.repaidInterest(), parseEther("0.6"));
    assert.equal(await f.pool.read.activeLoanCount(), 0n);
    assert.equal(await f.pool.read.lockedContributions([f.contributor.account.address]), 0n);
    assert.equal(await f.pool.read.totalUnlockedFunds(), parseEther("10"));
    assert.equal(await f.pool.read.pendingInterestGain([f.contributor.account.address]), parseEther("0.4"));
    assert.equal(await f.pool.read.compensationPoolBalance(), parseEther("0.4"));
  });
});
