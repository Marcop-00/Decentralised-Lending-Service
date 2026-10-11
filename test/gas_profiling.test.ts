import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { describe, it } from "node:test";
import { globalOptions } from "hardhat";
import type { Hash } from "viem";
import { deployProtocol, parseEther } from "./helpers/deployProtocol.ts";

describe("Gas profiling for every protocol operation", () => {
  it("records receipt gas, scenarios and reproducible build settings", async () => {
    const f = await deployProtocol();
    const operations: Record<string, string> = {};
    async function measure(name: string, hash: Hash) {
      const r = await f.receipt(hash);
      operations[name] = r.gasUsed.toString();
      assert.ok(r.gasUsed > 0n);
    }
    const account = f.contributor.account;
    const borrower = f.borrower.account;
    // A 34-character legacy mainnet address covers the longest address encoding
    // produced by the historical Bitcoin parser; 0 -> nonzero is the costly update.
    const btcAddress = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT";
    await measure("contribute_new", await f.pool.write.contribute({ account, value: parseEther("10") }));
    await measure("withdraw_partial", await f.pool.write.withdraw([parseEther("1")], { account }));
    await measure("requestUpdate", await f.oracle.write.requestUpdate([btcAddress], { account: borrower, value: await f.oracle.read.minFee() }));
    await measure("update_new_address", await f.oracle.write.update([btcAddress, 100n * 100_000_000n]));
    await measure("update_existing_address", await f.oracle.write.update([btcAddress, 99n * 100_000_000n]));
    await measure("createLoanProposal", await f.pool.write.createLoanProposal([
      borrower.address, btcAddress, parseEther("2"), 10n, 100n, 12n,
    ], { account: borrower }));
    await measure("voteOnProposal", await f.pool.write.voteOnProposal([1n, true], { account }));
    await f.networkHelpers.mine(12);
    await measure("executeApprovedLoan_approved", await f.pool.write.executeApprovedLoan([1n], { account: borrower }));
    const first = await f.loanFor(1n);
    await measure("repay_partial", await first.write.repay({ account: borrower, value: parseEther("1.1") }));
    await measure("repay_final", await first.write.repay({ account: borrower, value: parseEther("1.1") }));
    await measure("claimInterestGain", await f.pool.write.claimInterestGain({ account }));
    const second = await f.approveLoan(parseEther("1"), { duration: 2n });
    await f.networkHelpers.mine(3);
    await measure("markDefaulted", await second.loan.write.markDefaulted());
    await measure("requestCompensation_paid", await f.pool.write.requestCompensation([second.loan.address], { account }));
    await measure("requestCompensation_empty", await f.pool.write.requestCompensation([second.loan.address], { account }));
    await measure("repay_late", await second.loan.write.repay({ account: borrower, value: await second.loan.read.dueAmount() }));
    const rejected = await f.createProposal(parseEther("1"));
    await f.networkHelpers.mine(12);
    await measure("executeApprovedLoan_rejected", await f.pool.write.executeApprovedLoan([rejected], { account: borrower }));
    await measure("withdrawFees", await f.oracle.write.withdrawFees([f.owner.account.address]));
    const v2 = await f.viem.deployContract("FundingPoolV2");
    await measure("upgradeToAndCall", await f.pool.write.upgradeToAndCall([v2.address, "0x"]));
    await measure("terminate", await f.pool.write.terminate());
    await measure("withdraw_final", await f.pool.write.withdraw([await f.pool.read.unlockedBalanceOf([account.address])], { account }));
    const report = {
      environment: { hardhat: "3.18.1", solidity: "0.8.24", optimizerRuns: 200, evmVersion: "berlin", hardfork: "berlin", chainId: 202526, contributors: 1 },
      measurement: "Transaction receipts: gasUsed (includes intrinsic gas); values are gas units, not wei.",
      oracleFee: { measuredUpdateGas: operations.update_new_address, gasPriceWei: "100000000", minimumFeeWei: (BigInt(operations.update_new_address) * 100_000_000n).toString(), addressLength: btcAddress.length },
      operations,
    };
    // Coverage instruments the bytecode and changes gas consumption. Exercise
    // these paths but never overwrite production measurements with those costs.
    if (globalOptions.coverage) return;
    assert.equal(await f.oracle.read.UPDATE_GAS_ESTIMATE(), BigInt(operations.update_new_address));
    assert.equal(await f.oracle.read.minFee(), BigInt(report.oracleFee.minimumFeeWei));
    await mkdir("docs", { recursive: true });
    await writeFile("docs/gas-measurements.json", JSON.stringify(report, null, 2) + "\n");
    console.table(operations);
    console.log(`Oracle update fee calibration: ${report.oracleFee.minimumFeeWei} wei`);
  });
});
