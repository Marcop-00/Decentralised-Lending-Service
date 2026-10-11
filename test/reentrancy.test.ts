import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deployProtocol, parseEther } from "./helpers/deployProtocol.ts";

describe("Reentrancy against the real pool and its intentionally modified version", () => {
  it("drains the vulnerable pool but cannot steal from the production pool", async () => {
    const f = await deployProtocol();
    const vulnerableImplementation = await f.viem.deployContract("FundingPoolVulnerable");
    const vulnerableProxy = await f.viem.deployContract("FundingPoolProxy", [vulnerableImplementation.address, f.oracle.address]);
    // The vulnerable implementation retains the same public pool interface.
    const vulnerable = await f.viem.getContractAt("FundingPool", vulnerableProxy.address);
    for (const victim of [f.pool, vulnerable]) {
      await f.receipt(await victim.write.contribute({ account: f.contributor.account, value: parseEther("10") }));
      const attacker = await f.viem.deployContract("ReentrancyAttacker", [victim.address]);
      await f.receipt(await attacker.write.attack({ value: parseEther("1") }));
      const remaining = await f.publicClient.getBalance({ address: victim.address });
      const attackerBalance = await f.publicClient.getBalance({ address: attacker.address });
      if (victim.address === f.pool.address) {
        assert.equal(remaining, parseEther("10"));
        assert.equal(attackerBalance, parseEther("1"));
        assert.equal(await attacker.read.successfulReentries(), 0n);
        await f.receipt(await f.pool.write.withdraw([parseEther("10")], { account: f.contributor.account }));
      } else {
        assert.equal(remaining, 0n);
        assert.equal(attackerBalance, parseEther("11"));
        assert.equal(await attacker.read.successfulReentries(), 10n);
      }
    }
  });
});
