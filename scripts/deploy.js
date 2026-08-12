import hre from "hardhat";

async function main() {
  const { ethers } = hre;
  
  // Prendiamo i primi tre account forniti dal nodo Hardhat
  const [deployer, contributor, borrower] = await ethers.getSigners();

  console.log("Deploy in corso con l'account:", deployer.address);

  // 1. Deploy BitcoinOracle
  const minFee = ethers.parseEther("0.001");
  const Oracle = await ethers.getContractFactory("BitcoinOracle");
  const oracle = await Oracle.deploy(minFee);
  await oracle.waitForDeployment();
  const oracleAddress = await oracle.getAddress();
  console.log("✅ BitcoinOracle deployato a:", oracleAddress);

  // 2. Deploy FundingPool
  const Pool = await ethers.getContractFactory("FundingPool");
  const pool = await Pool.deploy();
  await pool.waitForDeployment();
  await pool.initialize(oracleAddress);
  const poolAddress = await pool.getAddress();
  console.log("✅ FundingPool deployato a:", poolAddress);

  // 3. Il Contributor versa 10 ETH nella pool per avere potere di voto
  console.log("Versamento di 10 ETH da parte del contributor...");
  await pool.connect(contributor).contribute({ value: ethers.parseEther("10") });
  console.log("✅ Versamento completato!");
  
  console.log("\n--- DATI PER GLI SCRIPT PYTHON ---");
  console.log("ORACLE_ADDRESS =", oracleAddress);
  console.log("POOL_ADDRESS =", poolAddress);
  console.log("OPERATOR_PRIVATE_KEY =", "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"); // Chiave dell'Account #0
  console.log("VOTER_PRIVATE_KEY =", "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"); // Chiave dell'Account #1
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});