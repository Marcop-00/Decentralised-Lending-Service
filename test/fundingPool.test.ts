import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deployProtocol, parseEther } from "./helpers/deployProtocol.ts";

describe("FundingPool end-to-end", () => {
  it("contribute -> propose -> vote -> execute -> repay", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("5") }));
    const { loan } = await f.approveLoan(parseEther("1"), { rate: 5n, duration: 3600n });
    assert.equal(await loan.read.status(), 1);
    assert.equal(await f.publicClient.getBalance({ address: f.pool.address }), parseEther("4"));
    await f.receipt(await loan.write.repay({ account: f.borrower.account, value: await loan.read.dueAmount() }));
    assert.equal(await loan.read.status(), 2);
    assert.equal(await f.publicClient.getBalance({ address: f.pool.address }), parseEther("5.05"));
    assert.equal(await f.pool.read.totalUnlockedFunds(), parseEther("5"));
    assert.equal(await f.pool.read.pendingInterestGain([f.contributor.account.address]), parseEther("0.025"));
    assert.equal(await f.pool.read.compensationPoolBalance(), parseEther("0.025"));
  });
});
