import hre from "hardhat";

async function main() {
  const { ethers } = hre;
  
  // We take the third account to act as the applicant (Borrower)
  const [deployer, contributor, borrower] = await ethers.getSigners();

  // Indirizzi estratti dai tuoi log
  const POOL_ADDRESS = "0xdc64a140aa3e981100a9beca4e685f962f0cf6c9";
  const ORACLE_ADDRESS = "0xcf7ed3acca5a467e9e704c703e8d87f634fb0fc9";

  const pool = await ethers.getContractAt("FundingPool", POOL_ADDRESS);
  const oracle = await ethers.getContractAt("BitcoinOracle", ORACLE_ADDRESS);

  const btcAddress = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"; // Satoshi's address

  console.log("1. The Borrower is creating a loan proposal (1 ETH at 5%)...");
  const tx1 = await pool.connect(borrower).createLoanProposal(
    borrower.address,
    btcAddress,
    ethers.parseEther("1"), // 1 ETH
    5, // 5% interest
    3600, // Duration
    12 // Voting period
  );
  await tx1.wait();
  console.log("✅ Proposal created! Check the Auto-Voter terminal!");

  console.log("\n2. The Borrower is requesting balance update from the oracle...");
  const minFee = await oracle.minFee();
  const tx2 = await oracle.connect(borrower).requestUpdate(btcAddress, { value: minFee });
  await tx2.wait();
  console.log("✅ Request sent! Check the Oracle terminal!");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});