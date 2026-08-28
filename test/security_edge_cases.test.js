import { expect } from "chai";
import assert from "assert";
import hre from "hardhat";
import helpers from "@nomicfoundation/hardhat-network-helpers";

const { ethers } = hre;

describe("Security and Edge Cases", function () {
  let pool, oracle;
  let deployer, attacker, borrower;

  beforeEach(async function () {
    [deployer, attacker, borrower] = await ethers.getSigners();
    
    const minFee = ethers.parseEther("0.001");
    const OracleFactory = await ethers.getContractFactory("BitcoinOracle");
    oracle = await OracleFactory.deploy(minFee);
    await oracle.waitForDeployment();

    const PoolFactory = await ethers.getContractFactory("FundingPool");
    pool = await PoolFactory.deploy();
    await pool.waitForDeployment();
    await pool.initialize(await oracle.getAddress());
  });

  describe("BitcoinOracle Access Control", function () {
    it("Should revert if an unauthorized user tries to update the balance", async function () {
      // The attacker tries to update the balance instead of the authorized operator
      await expect(
        oracle.connect(attacker).update("tb1qtestaddress", 500000n)
      ).to.be.revertedWithCustomError(oracle, "OwnableUnauthorizedAccount");
    });

    it("Should revert if the fee sent for an update request is too low", async function () {
      const minFee = await oracle.minFee();
      const badFee = minFee - 1n; // Just below the minimum
      
      await expect(
        oracle.connect(borrower).requestUpdate("tb1qtestaddress", { value: badFee })
      ).to.be.revertedWithCustomError(oracle, "InsufficientFee");
    });
  });

  describe("FundingPool Constraints", function () {
    it("Should revert if a contributor tries to vote twice", async function () {
      await pool.connect(attacker).contribute({ value: ethers.parseEther("5") });
      
      await pool.connect(borrower).createLoanProposal(
        borrower.address, "tb1qtest", ethers.parseEther("1"), 5, 3600, 12
      );

      // First vote: OK
      await pool.connect(attacker).voteOnProposal(1, true);
      
      // Second vote: Fails (assuming there is a check in the contract, e.g. "Already voted")
      // Use the generic error or revert depending on how Require was implemented
      await expect(
        pool.connect(attacker).voteOnProposal(1, true)
      ).to.be.reverted; 
    });
  });
});