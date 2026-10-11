import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deployProtocol, parseEther } from "./helpers/deployProtocol.ts";

describe("Advanced loan behaviors", () => {
  it("handles loan default and compensation correctly", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("10") }));
    const failed = await f.approveLoan(parseEther("5"), { duration: 50n });
    await f.receipt(await f.pool.write.contribute({ account: f.smallContributor.account, value: parseEther("5") }));
    const successful = await f.approveLoan(parseEther("1"), { rate: 50n, voters: [f.contributor, f.smallContributor] });
    await f.receipt(await successful.loan.write.repay({ account: f.borrower.account, value: await successful.loan.read.dueAmount() }));
    assert.equal(await f.pool.read.compensationPoolBalance(), parseEther("0.25"));
    await f.networkHelpers.mine(60);
    const before = await f.publicClient.getBalance({ address: f.contributor.account.address });
    const r = await f.receipt(await f.pool.write.requestCompensation([failed.loan.address], { account: f.contributor.account }));
    const after = await f.publicClient.getBalance({ address: f.contributor.account.address });
    assert.equal(after + r.gasUsed * r.effectiveGasPrice - before, parseEther("0.25"));
    assert.equal(await f.pool.read.compensationPoolBalance(), 0n);
    assert.equal(await failed.loan.read.status(), 3);
  });

  it("splits each installment and refunds highest initial contributors first", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.smallContributor.account, value: parseEther("2") }));
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("8") }));
    const { loan } = await f.approveLoan(parseEther("5"));
    await f.receipt(await loan.write.repay({ account: f.borrower.account, value: parseEther("1.1") }));
    assert.equal(await loan.read.repaidPrincipal(), parseEther("1"));
    assert.equal(await loan.read.repaidInterest(), parseEther("0.1"));
    assert.equal(await f.pool.read.lockedContributions([f.contributor.account.address]), parseEther("3"));
    assert.equal(await f.pool.read.lockedContributions([f.smallContributor.account.address]), parseEther("1"));
    assert.equal(await f.pool.read.pendingInterestGain([f.contributor.account.address]), parseEther("0.04"));
    assert.equal(await f.pool.read.pendingInterestGain([f.smallContributor.account.address]), parseEther("0.01"));
    assert.equal(await f.pool.read.compensationPoolBalance(), parseEther("0.05"));
  });
});
