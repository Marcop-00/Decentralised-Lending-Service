import { expect } from "chai";
import assert from "assert";
import hre from "hardhat";
import helpers from "@nomicfoundation/hardhat-network-helpers";
import { deployProtocol } from "./helpers/deployProtocol.js";

const { ethers, network } = hre;
const { time } = helpers;

describe("Advanced Loan Behaviors: Partial Repayment and Defaults", function () {
  let pool, oracle;
  let deployer, whaleContributor, smallContributor, borrower;

  beforeEach(async function () {
    [deployer, whaleContributor, smallContributor, borrower] = await ethers.getSigners();

    ({ pool, oracle } = await deployProtocol());
  });

  it("should handle Loan Default and Compensation correctly", async function () {
    // 1. Contributors deposit
    await pool.connect(whaleContributor).contribute({ value: ethers.parseEther("10") });
    
    // 2. Borrower creates loan proposal
    await pool.connect(borrower).createLoanProposal(
      borrower.address, "tb1qtest", ethers.parseEther("5"), 10, 50, 12 // 50 blocks duration
    );

    // 3. Vote and Oracle Update
    await pool.connect(whaleContributor).voteOnProposal(1, true);
    await oracle.connect(borrower).requestUpdate("tb1qtest", { value: ethers.parseEther("0.001") });
    await oracle.connect(deployer).update("tb1qtest", 500n * 100_000_000n); // Rich borrower

    // Mine blocks to pass voting
    for (let i = 0; i < 12; i++) {
      await network.provider.send("evm_mine");
    }

    // 4. Execute Loan
    await pool.connect(borrower).executeApprovedLoan(1);
    
    const proposal = await pool.proposals(1);
    const loanAddr = proposal.loanContract;
    const loan = await ethers.getContractAt("LoanContract", loanAddr);

    // We manually fund the compensation pool to simulate previous successful loans 
    // so there is actually something to compensate with.
    // In a real scenario, this would come from collateral of other loans.
    // We can simulate this by having another small loan succeed, or just forcing balance.
    // Let's do it by sending ETH directly to the pool? No, pool receive() might accept it but not update compensationPoolBalance.
    // We will let the compensation pool be 0, wait, if it's 0, requestCompensation fails with CompensationPoolEmpty.
    // Let's create a quick fake successful loan first to fund the compensation pool.
    
    await pool.connect(smallContributor).contribute({ value: ethers.parseEther("5") });
    await pool.connect(borrower).createLoanProposal(borrower.address, "tb1qtest", ethers.parseEther("1"), 50, 10, 12);
    await pool.connect(whaleContributor).voteOnProposal(2, true);
    await pool.connect(smallContributor).voteOnProposal(2, true);
    for (let i = 0; i < 12; i++) { await network.provider.send("evm_mine"); }
    await pool.connect(borrower).executeApprovedLoan(2);
    const proposal2 = await pool.proposals(2);
    const loan2 = await ethers.getContractAt("LoanContract", proposal2.loanContract);
    
    await deployer.sendTransaction({ to: borrower.address, value: ethers.parseEther("1") });
    await loan2.connect(borrower).repay({ value: await loan2.dueAmount() });
    
    // Now compensation pool has some funds (from the collateral portion of loan 2's interest).
    const compPoolBalance = await pool.compensationPoolBalance();
    assert.ok(compPoolBalance > 0n, "Compensation pool should have funds");

    // 5. Simulate Loan 1 Defaulting by mining blocks past its duration
    for (let i = 0; i < 60; i++) {
      await network.provider.send("evm_mine");
    }

    // 6. Whale Contributor requests compensation for the defaulted Loan 1
    const whaleBalBefore = await ethers.provider.getBalance(whaleContributor.address);
    const tx = await pool.connect(whaleContributor).requestCompensation(loanAddr);
    const receipt = await tx.wait();
    
    // Gas cost calculation
    const gasUsed = receipt.gasUsed * receipt.gasPrice;
    const whaleBalAfter = await ethers.provider.getBalance(whaleContributor.address);
    
    // Whale should have received compensation
    assert.ok(whaleBalAfter > whaleBalBefore - gasUsed, "Contributor should receive compensation");
  });

  it("should process Partial Repayments prioritizing highest contributors", async function () {
    // 1. Two contributors deposit different amounts
    await pool.connect(smallContributor).contribute({ value: ethers.parseEther("2") });
    await pool.connect(whaleContributor).contribute({ value: ethers.parseEther("8") });

    // 2. Borrower requests a loan of 5 ETH
    await pool.connect(borrower).createLoanProposal(
      borrower.address, "tb1qtest", ethers.parseEther("5"), 10, 50, 12
    );

    // Vote and execute
    await pool.connect(whaleContributor).voteOnProposal(1, true);
    await oracle.connect(borrower).requestUpdate("tb1qtest", { value: ethers.parseEther("0.001") });
    await oracle.connect(deployer).update("tb1qtest", 500n * 100_000_000n);
    
    for (let i = 0; i < 12; i++) { await network.provider.send("evm_mine"); }
    await pool.connect(borrower).executeApprovedLoan(1);
    
    const proposal = await pool.proposals(1);
    const loanAddr = proposal.loanContract;
    const loan = await ethers.getContractAt("LoanContract", loanAddr);

    // Initial locked balances
    const whaleLockedBefore = await pool.lockedContributions(whaleContributor.address);
    const smallLockedBefore = await pool.lockedContributions(smallContributor.address);
    
    assert.ok(whaleLockedBefore > smallLockedBefore, "Whale should have more locked funds");

    // 3. Borrower partially repays the loan (e.g., 2 ETH)
    // The base amount is refunded to highest locked contributor first (Whale).
    await deployer.sendTransaction({ to: borrower.address, value: ethers.parseEther("3") });
    await loan.connect(borrower).repay({ value: ethers.parseEther("2") });

    // 4. Check locked balances after partial repayment
    const whaleLockedAfter = await pool.lockedContributions(whaleContributor.address);
    const smallLockedAfter = await pool.lockedContributions(smallContributor.address);

    // Because Whale was the highest contributor, their locked amount should have decreased significantly more than Small
    // In fact, if the repayment was smaller than Whale's initial locked amount, ALL of it goes to Whale
    assert.ok(whaleLockedBefore - whaleLockedAfter > smallLockedBefore - smallLockedAfter, "Whale should receive priority refund");
  });
});
