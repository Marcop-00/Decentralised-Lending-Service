import { expect } from "chai";
import hre from "hardhat";
import { deployProtocol } from "./helpers/deployProtocol.js";

const { ethers, network } = hre;

async function mineVotingPeriod() {
  for (let i = 0; i < 12; i++) await network.provider.send("evm_mine");
}

async function updateBalance(oracle, owner, borrower, address, sats = 100n * 100_000_000n) {
  await oracle.connect(borrower).requestUpdate(address, { value: await oracle.minFee() });
  await oracle.connect(owner).update(address, sats);
}

describe("Trace compliance regressions", function () {
  it("uses current disposable funds, not ETH reserved for gains and compensation", async function () {
    const [owner, contributor, borrower] = await ethers.getSigners();
    const { pool, oracle } = await deployProtocol();
    const btcAddress = "tb1q-disposable";

    await pool.connect(contributor).contribute({ value: ethers.parseEther("5") });
    await pool.connect(borrower).createLoanProposal(
      borrower.address, btcAddress, ethers.parseEther("4"), 10, 20, 12,
    );
    await pool.connect(contributor).voteOnProposal(1, true);
    await updateBalance(oracle, owner, borrower, btcAddress);
    await mineVotingPeriod();
    await pool.connect(borrower).executeApprovedLoan(1);
    const firstLoan = await ethers.getContractAt("LoanContract", (await pool.proposals(1)).loanContract);
    await owner.sendTransaction({ to: borrower.address, value: ethers.parseEther("0.4") });
    await firstLoan.connect(borrower).repay({ value: await firstLoan.dueAmount() });

    // The pool physically holds compensation and unclaimed gain too, but only
    // 5 ETH are disposable and therefore fundable.
    await pool.connect(borrower).createLoanProposal(
      borrower.address, btcAddress, ethers.parseEther("5.1"), 10, 20, 12,
    );
    await pool.connect(contributor).voteOnProposal(2, true);
    await mineVotingPeriod();
    await pool.connect(borrower).executeApprovedLoan(2);

    const rejected = await pool.proposals(2);
    expect(rejected.executed).to.equal(true);
    expect(rejected.loanContract).to.equal(ethers.ZeroAddress);
  });

  it("makes defaults irreversible and never converts compensation into a second withdrawal claim", async function () {
    const [owner, whale, smallContributor, borrower] = await ethers.getSigners();
    const { pool, oracle } = await deployProtocol();
    const btcAddress = "tb1q-default";

    await pool.connect(whale).contribute({ value: ethers.parseEther("10") });
    await pool.connect(borrower).createLoanProposal(
      borrower.address, btcAddress, ethers.parseEther("5"), 10, 20, 12,
    );
    await pool.connect(whale).voteOnProposal(1, true);
    await updateBalance(oracle, owner, borrower, btcAddress);
    await mineVotingPeriod();
    await pool.connect(borrower).executeApprovedLoan(1);
    const failedLoan = await ethers.getContractAt("LoanContract", (await pool.proposals(1)).loanContract);

    // A successful second loan creates collateral in the compensation pool.
    await pool.connect(smallContributor).contribute({ value: ethers.parseEther("5") });
    await pool.connect(borrower).createLoanProposal(
      borrower.address, btcAddress, ethers.parseEther("1"), 50, 30, 12,
    );
    await pool.connect(whale).voteOnProposal(2, true);
    await pool.connect(smallContributor).voteOnProposal(2, true);
    await mineVotingPeriod();
    await pool.connect(borrower).executeApprovedLoan(2);
    const successfulLoan = await ethers.getContractAt("LoanContract", (await pool.proposals(2)).loanContract);
    await owner.sendTransaction({ to: borrower.address, value: ethers.parseEther("1") });
    await successfulLoan.connect(borrower).repay({ value: await successfulLoan.dueAmount() });

    for (let i = 0; i < 40; i++) await network.provider.send("evm_mine");
    const unlockedBefore = await pool.unlockedBalanceOf(whale.address);
    const totalBefore = await pool.totalContributed(whale.address);
    await pool.connect(whale).requestCompensation(await failedLoan.getAddress());

    expect(await failedLoan.status()).to.equal(3n); // Defaulted
    expect(await pool.unlockedBalanceOf(whale.address)).to.equal(unlockedBefore);
    expect(await pool.totalContributed(whale.address)).to.be.lessThan(totalBefore);

    await owner.sendTransaction({ to: borrower.address, value: ethers.parseEther("5.5") });
    await failedLoan.connect(borrower).repay({ value: await failedLoan.dueAmount() });
    expect(await failedLoan.status()).to.equal(3n);
    expect(await pool.isLoanFailed(1)).to.equal(true);
  });

  it("only terminates once all loans are resolved and still lets owners recover balances", async function () {
    const [owner, contributor, borrower] = await ethers.getSigners();
    const { pool, oracle } = await deployProtocol();
    const btcAddress = "tb1q-termination";

    await pool.connect(contributor).contribute({ value: ethers.parseEther("2") });
    await pool.connect(borrower).createLoanProposal(
      borrower.address, btcAddress, ethers.parseEther("1"), 10, 20, 12,
    );
    await pool.connect(contributor).voteOnProposal(1, true);
    await updateBalance(oracle, owner, borrower, btcAddress);
    await mineVotingPeriod();
    await pool.connect(borrower).executeApprovedLoan(1);
    await expect(pool.connect(owner).terminate()).to.be.revertedWithCustomError(pool, "ActiveLoansExist");

    const loan = await ethers.getContractAt("LoanContract", (await pool.proposals(1)).loanContract);
    await owner.sendTransaction({ to: borrower.address, value: ethers.parseEther("0.1") });
    await loan.connect(borrower).repay({ value: await loan.dueAmount() });
    await pool.connect(owner).terminate();
    await pool.connect(contributor).withdraw(ethers.parseEther("2"));
    expect(await pool.terminated()).to.equal(true);
  });
});
