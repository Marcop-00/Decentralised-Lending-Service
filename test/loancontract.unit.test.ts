import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deployProtocol, parseEther } from "./helpers/deployProtocol.ts";

describe("LoanContract unit tests", () => {
  it("calculates dueAmount correctly and enforces state transitions", async () => {
    const f = await deployProtocol();
    const principal = parseEther("1");
    const loan = await f.viem.deployContract("LoanContract", [
      f.contributor.account.address, f.borrower.account.address, principal, 5n, 3600n, 5n,
    ]);
    assert.equal(await loan.read.dueAmount(), parseEther("1.05"));
    await f.viem.assertions.revertWithCustomError(loan.write.fundLoan({ value: principal }), loan, "Unauthorized");
    await f.receipt(await loan.write.fundLoan({ account: f.contributor.account, value: principal }));
    assert.equal(await loan.read.status(), 1);
    await f.viem.assertions.revertWithCustomError(loan.write.repay({ account: f.borrower.account, value: 0n }), loan, "InvalidAmount");
  });
});
