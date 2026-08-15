import { expect } from "chai";
import assert from "assert";
import hre from "hardhat";
import helpers from "@nomicfoundation/hardhat-network-helpers";


const { ethers, network } = hre;
const { time } = helpers;

describe("FundingPool end-to-end", function () {
  it("contribute -> propose -> vote -> execute -> repay", async function () {
    const [deployer, contributor, borrower] = await ethers.getSigners();

    const minFee = ethers.parseEther("0.001");

    const OracleFactory = await ethers.getContractFactory("BitcoinOracle");
    const oracle = await OracleFactory.deploy(minFee);
    await oracle.waitForDeployment();

    const PoolFactory = await ethers.getContractFactory("FundingPool");
    const pool = await PoolFactory.deploy();
    await pool.waitForDeployment();
    await pool.initialize(await oracle.getAddress());

    // contributor contributes 5 ETH
    await pool.connect(contributor).contribute({ value: ethers.parseEther("5") });

    const principal = ethers.parseEther("1");
    const btcAddr = "tb1qtestaddress";

    // Borrower creates their own loan proposal
    const txCreate = await pool
      .connect(borrower)
      .createLoanProposal(borrower.address, btcAddr, principal, 5, 3600, 12);
    await txCreate.wait();

    // Contributor votes yes
    await pool.connect(contributor).voteOnProposal(1, true);

    // Update oracle so the borrower appears sufficiently liquid
    const SATS_PER_BTC = 100_000_000n;
    // 100 BTC in sats
    const sats = 100n * BigInt(SATS_PER_BTC);
    // 1. The borrower requests the update and pays the fee
    await oracle.connect(borrower).requestUpdate(btcAddr, { value: minFee });
    // 2. The oracle (deployer) processes off-chain and updates the value
    await oracle.connect(deployer).update(btcAddr, sats);

    // Mine enough blocks for the fixed 12-block voting window to finish.
    for (let i = 0; i < 12; i++) {
      await network.provider.send("evm_mine");
    }

    // Applicant executes the approved loan when voting period has passed
    const txExec = await pool.connect(borrower).executeApprovedLoan(1);
    await txExec.wait();

    const proposal = await pool.proposals(1);
    const loanAddr = proposal.loanContract;
    assert.strictEqual(typeof loanAddr, "string");

    const loan = await ethers.getContractAt("LoanContract", loanAddr);

    // Loan should be Funded (enum value 1)
    const status = await loan.status();
    // status is a BigInt
    assert.strictEqual(status, 1n);

    // Pool balance should have decreased by principal (5 - 1 = 4 ETH)
    const poolAddress = await pool.getAddress();
    const poolBalAfterFunding = await ethers.provider.getBalance(poolAddress);
    assert.strictEqual(poolBalAfterFunding, ethers.parseEther("4"));

    // Borrower needs a small extra amount to cover the interest portion of the debt.
    await deployer.sendTransaction({
      to: borrower.address,
      value: ethers.parseEther("0.05"),
    });

    // Borrower repays the loan (dueAmount = principal + interest)
    const due = await loan.dueAmount();

    // Simulate borrower repaying
    await loan.connect(borrower).repay({ value: due });

    // Pool balance should now be previous + due
    const poolBalAfterRepay = await ethers.provider.getBalance(poolAddress);
    const expected = ethers.parseEther("4") + due;
    assert.strictEqual(poolBalAfterRepay, expected);
  });
});
