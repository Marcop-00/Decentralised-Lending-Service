import { expect } from "chai";
import assert from "assert";
import hre from "hardhat";

const { ethers } = hre;

describe("LoanContract unit tests", function () {
  it("calculates dueAmount correctly and enforces state transitions", async function () {
    const [deployer, borrower, dummyPool] = await ethers.getSigners();

    const principal = ethers.parseEther("1");
    const interestBps = 500; // 5%
    const duration = 3600; // 1 hour

    const Loan = await ethers.getContractFactory("LoanContract");
    const loan = await Loan.deploy(dummyPool.address, borrower.address, principal, interestBps, duration, 50);
    await loan.waitForDeployment();

    // dueAmount = principal + principal * interestBps / 10000
    const due = await loan.dueAmount();
    const expected = principal + (principal * BigInt(interestBps)) / 10000n;
    assert.strictEqual(due, expected);

    // fundLoan must be called by pool and with exact principal
    await assert.rejects(async () => {
      await loan.connect(deployer).fundLoan({ value: principal }); // called by deployer (not pool)
    });

    // Simulate pool calling fundLoan: connect with dummyPool signer
    await loan.connect(dummyPool).fundLoan({ value: principal });
    const status = await loan.status();
    assert.strictEqual(status, 1n); // Funded = 1

    // repay should revert if msg.value is 0
    await assert.rejects(async () => {
      await loan.connect(borrower).repay({ value: 0 });
    });
  });
});