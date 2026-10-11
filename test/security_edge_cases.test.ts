import { describe, it } from "node:test";
import { deployProtocol, parseEther } from "./helpers/deployProtocol.ts";

describe("Security and edge cases", () => {
  it("rejects unauthorized oracle updates", async () => {
    const f = await deployProtocol();
    await f.viem.assertions.revertWithCustomError(
      f.oracle.write.update(["1Test", 500000n], { account: f.contributor.account }), f.oracle, "OwnableUnauthorizedAccount",
    );
  });
  it("rejects update requests below the minimum fee", async () => {
    const f = await deployProtocol();
    await f.viem.assertions.revertWithCustomError(
      f.oracle.write.requestUpdate(["1Test"], { account: f.borrower.account, value: await f.oracle.read.minFee() - 1n }),
      f.oracle, "InsufficientFee",
    );
  });
  it("prevents double voting", async () => {
    const f = await deployProtocol();
    await f.receipt(await f.pool.write.contribute({ account: f.contributor.account, value: parseEther("5") }));
    const id = await f.createProposal(parseEther("1"));
    await f.receipt(await f.pool.write.voteOnProposal([id, true], { account: f.contributor.account }));
    await f.viem.assertions.revertWithCustomError(
      f.pool.write.voteOnProposal([id, true], { account: f.contributor.account }), f.pool, "AlreadyVoted",
    );
  });
});
