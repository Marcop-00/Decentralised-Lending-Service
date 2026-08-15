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
      // L'attaccante cerca di aggiornare il saldo al posto dell'operatore autorizzato
      await expect(
        oracle.connect(attacker).update("tb1qtestaddress", 500000n)
      ).to.be.revertedWithCustomError(oracle, "OwnableUnauthorizedAccount");
    });

    it("Should revert if the fee sent for an update request is too low", async function () {
      const minFee = await oracle.minFee();
      const badFee = minFee - 1n; // Appena sotto il minimo
      
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

      // Primo voto: OK
      await pool.connect(attacker).voteOnProposal(1, true);
      
      // Secondo voto: Fallisce (assumendo che tu abbia un controllo nel contratto, es. "Already voted")
      // Usa l'errore o il revert generico a seconda di come hai implementato Require
      await expect(
        pool.connect(attacker).voteOnProposal(1, true)
      ).to.be.reverted; 
    });
  });
});