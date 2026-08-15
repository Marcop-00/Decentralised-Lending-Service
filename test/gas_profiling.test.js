import { expect } from "chai";
import hre from "hardhat";
import helpers from "@nomicfoundation/hardhat-network-helpers";

const { ethers, network } = hre;
const { time } = helpers;

describe("Gas Profiling Evaluation", function () {
  let pool, oracle;
  let deployer, contributor, borrower;

  before(async function () {
    [deployer, contributor, borrower] = await ethers.getSigners();
    
    // Deploy Oracle
    const minFee = ethers.parseEther("0.001");
    const OracleFactory = await ethers.getContractFactory("BitcoinOracle");
    oracle = await OracleFactory.deploy(minFee);
    await oracle.waitForDeployment();

    // Deploy FundingPool
    const PoolFactory = await ethers.getContractFactory("FundingPool");
    pool = await PoolFactory.deploy();
    await pool.waitForDeployment();
    await pool.initialize(await oracle.getAddress());
  });

  it("Should measure and log gas costs for main operations", async function () {
    console.log("\n--- GAS EVALUATION RESULTS ---");

    // 1. Contribute
    let tx = await pool.connect(contributor).contribute({ value: ethers.parseEther("10") });
    let receipt = await tx.wait();
    console.log(`contribute() gas used: ${receipt.gasUsed}`);

    // 2. Withdraw
    tx = await pool.connect(contributor).withdraw(ethers.parseEther("1"));
    receipt = await tx.wait();
    console.log(`withdraw() gas used: ${receipt.gasUsed}`);

    // 3. Create Loan Proposal
    const principal = ethers.parseEther("2");
    tx = await pool.connect(borrower).createLoanProposal(
      borrower.address,
      "tb1qtestaddress",
      principal,
      5, // interest rate
      3600, // duration blocks
      12 // voting period blocks
    );
    receipt = await tx.wait();
    console.log(`createLoanProposal() gas used: ${receipt.gasUsed}`);

    // 4. Vote on Proposal
    tx = await pool.connect(contributor).voteOnProposal(1, true);
    receipt = await tx.wait();
    console.log(`voteOnProposal() gas used: ${receipt.gasUsed}`);

    // Oracle Update (Setup for execution)
    const minFee = ethers.parseEther("0.001");
    // 1. The borrower requests the update by paying the fee
    await oracle.connect(borrower).requestUpdate("tb1qtestaddress", { value: minFee });
    // 2. The oracle updates the data off-chain
    await oracle.connect(deployer).update("tb1qtestaddress", 100n * 100_000_000n);

    // Mine blocks to pass the voting deadline
    for (let i = 0; i < 12; i++) {
      await network.provider.send("evm_mine");
    }

    // 5. Execute Approved Loan
    tx = await pool.connect(borrower).executeApprovedLoan(1);
    receipt = await tx.wait();
    console.log(`executeApprovedLoan() gas used: ${receipt.gasUsed}`);

    // 6. Repay Loan
    const proposal = await pool.proposals(1);
    const loan = await ethers.getContractAt("LoanContract", proposal.loanContract);
    
    // Send some extra ETH to the borrower to pay interests
    await deployer.sendTransaction({ to: borrower.address, value: ethers.parseEther("1") });
    
    const due = await loan.dueAmount();
    tx = await loan.connect(borrower).repay({ value: due });
    receipt = await tx.wait();
    console.log(`repay() gas used: ${receipt.gasUsed}`);
    console.log("------------------------------\n");
  });
});