import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deployProtocol, parseEther } from "./helpers/deployProtocol.ts";

describe("Transaction receipt gas sanity checks", () => {
  it("measures gas actually consumed rather than the transaction gas limit", async () => {
    const f = await deployProtocol();
    const hash = await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("2"), gas: 1_000_000n });
    const receipt = await f.receipt(hash);
    const tx = await f.publicClient.getTransaction({ hash });
    assert.ok(receipt.gasUsed > 21_000n);
    assert.ok(receipt.gasUsed < tx.gas);
    const before = await f.publicClient.getBalance({ address: f.contributor.account.address });
    const withdrawal = await f.receipt(await f.pool.write.withdraw([parseEther("1")], { account: f.contributor.account }));
    const after = await f.publicClient.getBalance({ address: f.contributor.account.address });
    assert.equal(after - before, parseEther("1") - withdrawal.gasUsed * withdrawal.effectiveGasPrice);
  });
});
