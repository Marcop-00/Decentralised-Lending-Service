import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deployProtocol, parseEther } from "./helpers/deployProtocol.ts";

describe("UUPS upgrade and initialization", () => {
  it("only lets the owner upgrade and preserves balances, proposals and active loans", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("5") }));
    const { id, loan } = await f.approveLoan(parseEther("2"));
    const v2 = await f.viem.deployContract("FundingPoolV2");
    await f.viem.assertions.revertWithCustomError(
      f.pool.write.upgradeToAndCall([v2.address, "0x"], { account: f.contributor.account }), f.pool, "OwnableUnauthorizedAccount",
    );
    const before = {
      balance: await f.publicClient.getBalance({ address: f.pool.address }),
      proposal: await f.pool.read.proposals([id]),
      position: await f.pool.read.totalContributed([f.contributor.account.address]),
      locked: await f.pool.read.lockedContributions([f.contributor.account.address]),
    };
    await f.receipt(await f.pool.write.upgradeToAndCall([v2.address, "0x"]));
    const upgraded = await f.viem.getContractAt("FundingPoolV2", f.pool.address);
    assert.equal(await upgraded.read.version(), 2n);
    assert.equal(await f.publicClient.getBalance({ address: upgraded.address }), before.balance);
    assert.deepEqual(await upgraded.read.proposals([id]), before.proposal);
    assert.equal(await upgraded.read.totalContributed([f.contributor.account.address]), before.position);
    assert.equal(await upgraded.read.lockedContributions([f.contributor.account.address]), before.locked);
    assert.equal(await upgraded.read.activeLoanCount(), 1n);
    await f.receipt(await loan.write.repay({ account: f.borrower.account, value: await loan.read.dueAmount() }));
    assert.equal(await upgraded.read.activeLoanCount(), 0n);
    assert.equal(await upgraded.read.unlockedBalanceOf([f.contributor.account.address]), parseEther("5"));
    await f.receipt(await upgraded.write.withdraw([parseEther("5")], { account: f.contributor.account }));
  });

  it("disables initialization of implementations and repeated proxy initialization", async () => {
    const f = await deployProtocol();
    await f.viem.assertions.revertWithCustomError(
      f.implementation.write.initialize([f.oracle.address]), f.implementation, "InvalidInitialization",
    );
    await f.viem.assertions.revertWithCustomError(
      f.pool.write.initialize([f.oracle.address]), f.pool, "InvalidInitialization",
    );
    assert.equal((await f.pool.read.owner()).toLowerCase(), f.owner.account.address.toLowerCase());
  });
});
