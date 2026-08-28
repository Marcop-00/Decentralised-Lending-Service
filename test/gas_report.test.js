import { expect } from "chai";
import assert from "assert";
import hre from "hardhat";
import helpers from "@nomicfoundation/hardhat-network-helpers";
import { deployProtocol } from "./helpers/deployProtocol.js";

const { ethers, network } = hre;
const { time } = helpers;

describe("Gas report sanity checks", function () {
  it("runs the main operations and stores gas data", async function () {
    const [deployer, contributor, borrower] = await ethers.getSigners();
    const { pool, oracle } = await deployProtocol();
    const minFee = await oracle.minFee();

    const depositAmount = ethers.parseEther("2");
    const tx1 = await pool.connect(contributor).contribute({ value: depositAmount });
    await tx1.wait();

    const tx2 = await pool.connect(borrower).createLoanProposal(
      borrower.address,
      "tb1qgasmeasure",
      ethers.parseEther("1"),
      5,
      3600,
      12,
    );
    await tx2.wait();

    const tx3 = await pool.connect(contributor).voteOnProposal(1, true);
    await tx3.wait();

    await oracle.connect(borrower).requestUpdate("tb1qgasmeasure", { value: minFee });
    await oracle.connect(deployer).update("tb1qgasmeasure", 100_000_000n);
    for (let i = 0; i < 12; i++) {
      await network.provider.send("evm_mine");
    }

    const tx4 = await pool.connect(borrower).executeApprovedLoan(1);
    await tx4.wait();

    const proposal = await pool.proposals(1);
    const loan = await ethers.getContractAt("LoanContract", proposal.loanContract);
    const due = await loan.dueAmount();
    const tx5 = await loan.connect(borrower).repay({ value: due });
    await tx5.wait();

    assert.ok(tx1.gasLimit > 0n);
    assert.ok(tx2.gasLimit > 0n);
    assert.ok(tx3.gasLimit > 0n);
    assert.ok(tx4.gasLimit > 0n);
    assert.ok(tx5.gasLimit > 0n);
  });
});
