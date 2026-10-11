import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deployProtocol, parseEther, zeroAddress } from "./helpers/deployProtocol.ts";

describe("Requirement boundaries and accounting", () => {
  it("requires deposits strictly above 100000 wei and removes fully withdrawn contributors", async () => {
    const f = await deployProtocol();
    await f.viem.assertions.revertWithCustomError(
      f.pool.write.contribute({ account: f.contributor.account, value: 100_000n }), f.pool, "DepositTooLow",
    );
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: 100_001n }));
    assert.equal(await f.pool.read.isContributor([f.contributor.account.address]), true);
    await f.viem.assertions.revertWithCustomError(
      f.pool.write.withdraw([100_002n], { account: f.contributor.account }), f.pool, "InsufficientUnlockedBalance",
    );
    await f.receipt(await f.pool.write.withdraw([100_001n], { account: f.contributor.account }));
    assert.equal(await f.pool.read.isContributor([f.contributor.account.address]), false);
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: 100_001n }));
    assert.equal(await f.pool.read.isContributor([f.contributor.account.address]), true);
    assert.equal(await f.pool.read.totalUnlockedFunds(), 100_001n);
  });

  it("requires the original borrower to resolve and repay, and checks the exact BTC liquidity threshold", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("60") }));
    await f.updateOracle("1TestLiquidityAddress", 100_000_000n);
    for (const [principal, accepted] of [[parseEther("30") + 1n, false], [parseEther("30"), true]] as const) {
      const id = await f.createProposal(principal);
      await f.receipt(await f.pool.write.voteOnProposal([id, true], { account: f.contributor.account }));
      await f.networkHelpers.mine(12);
      await f.viem.assertions.revertWithCustomError(
        f.pool.write.executeApprovedLoan([id], { account: f.smallContributor.account }), f.pool, "Unauthorized",
      );
      await f.receipt(await f.pool.write.executeApprovedLoan([id], { account: f.borrower.account }));
      assert.equal((await f.proposal(id)).loanContract !== zeroAddress, accepted);
      if (accepted) {
        const loan = await f.loanFor(id);
        await f.viem.assertions.revertWithCustomError(
          loan.write.repay({ account: f.contributor.account, value: 1n }), loan, "Unauthorized",
        );
      }
    }
  });

  it("breaks equal initial shares by descending address and preserves that order across installments", async () => {
    const f = await deployProtocol();
    for (const account of [f.contributor.account, f.smallContributor.account]) {
      await f.receipt(await f.pool.write.contribute({ account, value: parseEther("2") }));
    }
    const { loan } = await f.approveLoan(parseEther("2"), { voters: [f.contributor, f.smallContributor] });
    const [higher, lower] = [f.contributor.account.address, f.smallContributor.account.address].sort((a, b) => BigInt(a) > BigInt(b) ? -1 : 1);
    await f.receipt(await loan.write.repay({ account: f.borrower.account, value: parseEther("0.55") }));
    assert.equal(await f.pool.read.lockedContributions([higher]), parseEther("0.5"));
    assert.equal(await f.pool.read.lockedContributions([lower]), parseEther("1"));
    await f.receipt(await loan.write.repay({ account: f.borrower.account, value: parseEther("0.55") }));
    assert.equal(await f.pool.read.lockedContributions([higher]), 0n);
    assert.equal(await f.pool.read.lockedContributions([lower]), parseEther("1"));
  });

  it("credits overpayment to compensation without enlarging contributors' principal or gain", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("2") }));
    const { loan } = await f.approveLoan(parseEther("1"));
    await f.receipt(await loan.write.repay({ account: f.borrower.account, value: parseEther("2") }));
    assert.equal(await f.pool.read.totalUnlockedFunds(), parseEther("2"));
    assert.equal(await f.pool.read.pendingInterestGain([f.contributor.account.address]), parseEther("0.05"));
    assert.equal(await f.pool.read.compensationPoolBalance(), parseEther("0.95"));
    assert.equal(await loan.read.status(), 2);
  });

  it("clamps collateral to 1..100 and keeps each existing loan's snapshot", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("100") }));
    const first = await f.approveLoan(parseEther("1"), { duration: 10_000n });
    assert.equal(await first.loan.read.collateralPercentage(), 50n);
    for (let i = 0; i < 11; i++) {
      const { loan } = await f.approveLoan(parseEther("1"));
      await f.receipt(await loan.write.repay({ account: f.borrower.account, value: await loan.read.dueAmount() }));
    }
    assert.equal(await f.pool.read.collateralPercentage(), 1n);
    assert.equal(await first.loan.read.collateralPercentage(), 50n);
    for (let i = 0; i < 21; i++) {
      const { loan } = await f.approveLoan(parseEther("1"), { duration: 1n });
      await f.networkHelpers.mine(2);
      await f.receipt(await loan.write.markDefaulted());
    }
    assert.equal(await f.pool.read.collateralPercentage(), 100n);
    assert.equal(await f.pool.read.failedLoanCount(), 21n);
    assert.equal(await first.loan.read.collateralPercentage(), 50n);
  });
});
