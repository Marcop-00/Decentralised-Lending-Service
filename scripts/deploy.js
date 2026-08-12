const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying contracts with account:", deployer.address);

  const minFee = hre.ethers.parseEther("0.001");

  const Oracle = await hre.ethers.getContractFactory("BitcoinOracle");
  const oracle = await Oracle.deploy(minFee);
  await oracle.deployed();
  console.log("BitcoinOracle deployed to:", oracle.address);

  const Pool = await hre.ethers.getContractFactory("FundingPool");
  const pool = await Pool.deploy(oracle.address);
  await pool.deployed();
  console.log("FundingPool deployed to:", pool.address);

  console.log("Deployment complete. Addresses:\n  Oracle:\", oracle.address, "\n  Pool:\", pool.address);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
