const { ethers } = require("hardhat");
const assert = require("assert");

describe("LoanContract unit tests", function () {
  it("calculates dueAmount correctly and enforces state transitions", async function () {
    const [deployer, borrower, pool] = await ethers.getSigners();

    const principal = ethers.parseEther("1");
    const interestBps = 500; // 5%
    const duration = 3600; // 1 hour

    const Loan = await ethers.getContractFactory("LoanContract");
    const loan = await Loan.deploy(pool.address, borrower.address, principal, interestBps, duration);
    await loan.waitForDeployment();

    // dueAmount = principal + principal * interestBps / 10000
    const due = await loan.dueAmount();
    const expected = principal + (principal * BigInt(interestBps)) / 10000n;
    assert.strictEqual(due, expected);

    // fundLoan must be called by pool and with exact principal
    await assert.rejects(async () => {
      await loan.fundLoan({ value: principal }); // called by deployer (not pool)
    });

    // Simulate pool calling fundLoan: connect with pool signer
    await loan.connect(pool).fundLoan({ value: principal });
    const status = await loan.status();
    // enum: Created=0, Funded=1
    assert.strictEqual(status, 1n);

    // repay should require exact due amount
    await assert.rejects(async () => {
      await loan.connect(borrower).repay({ value: principal });
    });

    await loan.connect(borrower).repay({ value: due });
    const status2 = await loan.status();
    assert.strictEqual(status2, 2n); // Repaid
  });
});
