import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deployProtocol, parseEther, zeroAddress } from "./helpers/deployProtocol.ts";

describe("Trace compliance regressions", () => {
  it("uses disposable funds, excluding reserved gains and compensation", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("5") }));
    const first = await f.approveLoan(parseEther("4"));
    await f.receipt(await first.loan.write.repay({ account: f.borrower.account, value: await first.loan.read.dueAmount() }));
    const id = await f.createProposal(parseEther("5.1"));
    await f.receipt(await f.pool.write.voteOnProposal([id, true], { account: f.contributor.account }));
    await f.networkHelpers.mine(12);
    await f.receipt(await f.pool.write.executeApprovedLoan([id], { account: f.borrower.account }));
    const p = await f.proposal(id);
    assert.equal(p.executed, true);
    assert.equal(p.loanContract, zeroAddress);
  });

  it("deducts proportional rounding from the actual loan principal", async () => {
    const f = await deployProtocol();
    const third = f.wallets[4];
    const deposits = [parseEther("2"), parseEther("3"), parseEther("6")];
    for (const [index, wallet] of [f.contributor, f.smallContributor, third].entries()) {
      await f.receipt(await f.pool.write.contribute({ account: wallet.account, value: deposits[index] }));
    }
    const requested = parseEther("4");
    const { loan } = await f.approveLoan(requested, { voters: [f.contributor, f.smallContributor, third] });
    assert.ok(await loan.read.principal() < requested);
    assert.equal(await loan.read.principal(), deposits.reduce((sum, deposit) => sum + deposit * requested / parseEther("11"), 0n));
  });

  it("makes defaults irreversible and avoids a second claim for compensated funds", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("10") }));
    const failed = await f.approveLoan(parseEther("5"), { duration: 20n });
    await f.receipt(await f.pool.write.contribute({ account: f.smallContributor.account, value: parseEther("5") }));
    const good = await f.approveLoan(parseEther("1"), { rate: 50n, voters: [f.contributor, f.smallContributor] });
    await f.receipt(await good.loan.write.repay({ account: f.borrower.account, value: await good.loan.read.dueAmount() }));
    await f.networkHelpers.mine(40);
    const available = await f.pool.read.unlockedBalanceOf([f.contributor.account.address]);
    const total = await f.pool.read.totalContributed([f.contributor.account.address]);
    await f.receipt(await f.pool.write.requestCompensation([failed.loan.address], { account: f.contributor.account }));
    assert.equal(await failed.loan.read.status(), 3);
    assert.equal(await f.pool.read.unlockedBalanceOf([f.contributor.account.address]), available);
    assert.equal(await f.pool.read.totalContributed([f.contributor.account.address]), total - parseEther("0.25"));
    await f.receipt(await failed.loan.write.repay({ account: f.borrower.account, value: await failed.loan.read.dueAmount() }));
    assert.equal(await failed.loan.read.status(), 3);
    assert.equal(await f.pool.read.isLoanFailed([failed.id]), true);
  });

  it("terminates after loans resolve while preserving withdrawal rights", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("2") }));
    const { loan } = await f.approveLoan(parseEther("1"));
    await f.viem.assertions.revertWithCustomError(f.pool.write.terminate(), f.pool, "ActiveLoansExist");
    await f.receipt(await loan.write.repay({ account: f.borrower.account, value: await loan.read.dueAmount() }));
    await f.receipt(await f.pool.write.terminate());
    await f.receipt(await f.pool.write.withdraw([parseEther("2")], { account: f.contributor.account }));
    assert.equal(await f.pool.read.terminated(), true);
    assert.equal(await f.pool.read.totalUnlockedFunds(), 0n);
    await f.viem.assertions.revertWithCustomError(
      f.pool.write.contribute({ account: f.contributor.account, value: parseEther("1") }), f.pool, "ContractTerminated",
    );
    await f.receipt(await f.pool.write.claimInterestGain({ account: f.contributor.account }));
  });

  it("marks a loan failed on its first late partial repayment", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("2") }));
    const { id, loan } = await f.approveLoan(parseEther("1"), { duration: 3n });
    await f.networkHelpers.mine(4);
    await f.receipt(await loan.write.repay({ account: f.borrower.account, value: 1n }));
    assert.equal(await loan.read.status(), 3);
    assert.equal(await f.pool.read.isLoanFailed([id]), true);
    assert.equal(await f.pool.read.collateralPercentage(), 55n);
  });

  it("counts current balances when deposits change after voting", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("6") }));
    await f.receipt(await f.pool.write.contribute({ account: f.smallContributor.account, value: parseEther("4") }));
    const id = await f.createProposal(parseEther("1"));
    await f.receipt(await f.pool.write.voteOnProposal([id, true], { account: f.contributor.account }));
    await f.receipt(await f.pool.write.withdraw([parseEther("4")], { account: f.contributor.account }));
    await f.updateOracle();
    await f.networkHelpers.mine(12);
    await f.receipt(await f.pool.write.executeApprovedLoan([id], { account: f.borrower.account }));
    const p = await f.proposal(id);
    assert.equal(p.yesVotes, parseEther("2"));
    assert.equal(p.noVotes, parseEther("4"));
    assert.equal(p.loanContract, zeroAddress);
    assert.equal(p.executed, true);
  });

  it("rejects ties and treats nonvoters as rejecting the proposal", async () => {
    const f = await deployProtocol();
    for (const account of [f.contributor.account, f.smallContributor.account]) {
      await f.receipt(await f.pool.write.contribute({ account, value: parseEther("1") }));
    }
    const id = await f.createProposal(parseEther("1"));
    await f.receipt(await f.pool.write.voteOnProposal([id, true], { account: f.contributor.account }));
    await f.updateOracle();
    await f.networkHelpers.mine(12);
    await f.receipt(await f.pool.write.executeApprovedLoan([id], { account: f.borrower.account }));
    assert.equal((await f.proposal(id)).loanContract, zeroAddress);
    await f.viem.assertions.revertWithCustomError(
      f.pool.write.executeApprovedLoan([id], { account: f.borrower.account }), f.pool, "InvalidState",
    );
  });

  it("accepts a locked contributor's zero-weight vote and reweights it on repayment", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("6") }));
    await f.receipt(await f.pool.write.contribute({ account: f.smallContributor.account, value: parseEther("4") }));
    const first = await f.approveLoan(parseEther("10"), { voters: [f.contributor, f.smallContributor] });
    const id = await f.createProposal(parseEther("1"));
    assert.equal(await f.pool.read.votingPowerOf([f.contributor.account.address]), 0n);
    await f.receipt(await f.pool.write.voteOnProposal([id, true], { account: f.contributor.account }));
    assert.equal(await f.pool.read.hasVoted([id, f.contributor.account.address]), true);
    await f.receipt(await first.loan.write.repay({ account: f.borrower.account, value: await first.loan.read.dueAmount() }));
    await f.networkHelpers.mine(12);
    await f.receipt(await f.pool.write.executeApprovedLoan([id], { account: f.borrower.account }));
    assert.equal((await f.proposal(id)).yesVotes, parseEther("6"));
    assert.notEqual((await f.proposal(id)).loanContract, zeroAddress);
  });

  it("allows votes after twelve blocks until resolution and then closes voting", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("2") }));
    const id = await f.createProposal(parseEther("1"));
    await f.viem.assertions.revertWithCustomError(
      f.pool.write.executeApprovedLoan([id], { account: f.borrower.account }), f.pool, "VotingStillActive",
    );
    await f.updateOracle();
    await f.networkHelpers.mine(12);
    await f.receipt(await f.pool.write.voteOnProposal([id, true], { account: f.contributor.account }));
    await f.receipt(await f.pool.write.executeApprovedLoan([id], { account: f.borrower.account }));
    await f.viem.assertions.revertWithCustomError(
      f.pool.write.voteOnProposal([id, true], { account: f.smallContributor.account }), f.pool, "VotingClosed",
    );
  });

  it("records an unpaid default even when the compensation pool is empty", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("2") }));
    const { id, loan } = await f.approveLoan(parseEther("1"), { duration: 3n });
    await f.networkHelpers.mine(4);
    await f.receipt(await f.pool.write.requestCompensation([loan.address], { account: f.contributor.account }));
    assert.equal(await loan.read.status(), 3);
    assert.equal(await f.pool.read.isLoanFailed([id]), true);
    assert.equal(await f.pool.read.failedLoanCount(), 1n);
    assert.equal(await f.pool.read.collateralPercentage(), 55n);
    await f.receipt(await f.pool.write.requestCompensation([loan.address], { account: f.contributor.account }));
    assert.equal(await f.pool.read.failedLoanCount(), 1n);
    assert.equal(await f.pool.read.collateralPercentage(), 55n);
  });

  it("permits repeated compensation after refills and forfeits only amounts actually paid", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("10") }));
    const failed = await f.approveLoan(parseEther("5"), { duration: 2n });
    for (let i = 0; i < 2; i++) {
      const good = await f.approveLoan(parseEther("1"), { rate: 50n });
      await f.receipt(await good.loan.write.repay({ account: f.borrower.account, value: await good.loan.read.dueAmount() }));
      await f.receipt(await f.pool.write.requestCompensation([failed.loan.address], { account: f.contributor.account }));
    }
    assert.equal(await f.pool.read.loanContributions([failed.id, f.contributor.account.address]), parseEther("4.5"));
    assert.equal(await f.pool.read.totalContributed([f.contributor.account.address]), parseEther("9.5"));
    await f.receipt(await failed.loan.write.repay({ account: f.borrower.account, value: await failed.loan.read.dueAmount() }));
    assert.equal(await f.pool.read.unlockedBalanceOf([f.contributor.account.address]), parseEther("9.5"));
    assert.equal(await f.pool.read.compensationPoolBalance(), parseEther("0.75"));
    assert.equal(await failed.loan.read.status(), 3);
  });
});
