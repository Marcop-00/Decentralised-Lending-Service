import hre from "hardhat";
import fs from "fs";
import path from "path";

async function main() {
  const { ethers } = hre;
  
  // 1. L'account pre-finanziato sbloccato su Geth
  const PREFUNDED_ADDRESS = "0xd278d247a52c550508ea2b2c9321d816238fb523";
  
  console.log("⚙️  Generazione di nuovi account per il sistema...");
  // 2. Creiamo nuovi wallet casuali (non usiamo quello del prof per il deploy!)
  const deployer = ethers.Wallet.createRandom().connect(ethers.provider);
  const contributor = ethers.Wallet.createRandom().connect(ethers.provider);
  const borrower = ethers.Wallet.createRandom().connect(ethers.provider);

  console.log(`- Nuovo Deployer: ${deployer.address}`);
  console.log(`- Nuovo Contributor: ${contributor.address}`);

  console.log("\n💸 Trasferimento fondi dall'account pre-finanziato ai nuovi account...");
  // 3. Inviamo i fondi usando il metodo RPC grezzo (poiché la chiave privata non è in Ethers ma nel Keystore di Geth)
  const fundAmount = "0x" + ethers.parseEther("100").toString(16); // Formattazione esadecimale stretta
  
  await ethers.provider.send("eth_sendTransaction", [{ from: PREFUNDED_ADDRESS, to: deployer.address, value: fundAmount }]);
  await ethers.provider.send("eth_sendTransaction", [{ from: PREFUNDED_ADDRESS, to: contributor.address, value: fundAmount }]);
  await ethers.provider.send("eth_sendTransaction", [{ from: PREFUNDED_ADDRESS, to: borrower.address, value: fundAmount }]);
  
  console.log("⏳ Attesa del mining della transazione di finanziamento (circa 10 secondi)...");
  // Aspettiamo che il blocco venga minato (il genesis ha block time a 10s)
  await new Promise(r => setTimeout(r, 12000));

  console.log("\n🚀 Avvio deploy dei contratti con il nuovo account Deployer...");
  // Da qui in poi, usiamo l'account `deployer` appena creato, RISPETTANDO LA TRACCIA!
  const minFee = ethers.parseEther("0.001");
  const Oracle = await ethers.getContractFactory("BitcoinOracle", deployer);
  const oracle = await Oracle.deploy(minFee);
  await oracle.waitForDeployment();
  const oracleAddress = await oracle.getAddress();
  console.log("✅ BitcoinOracle deployato a:", oracleAddress);

  const Pool = await ethers.getContractFactory("FundingPool", deployer);
  const pool = await Pool.deploy();
  await pool.waitForDeployment();
  await pool.initialize(oracleAddress);
  const poolAddress = await pool.getAddress();
  console.log("✅ FundingPool deployata a:", poolAddress);

  console.log("⚙️  Generazione automatica dei file .env...");
  const envContent = `ETH_RPC_URL=http://127.0.0.1:8545
ORACLE_ADDRESS=${oracleAddress}
POOL_ADDRESS=${poolAddress}
OPERATOR_PRIVATE_KEY=${deployer.privateKey}
VOTER_PRIVATE_KEY=${contributor.privateKey}
BLK_DAT_DIR=../../bitcoin
`;

  fs.writeFileSync(path.join(process.cwd(), "python", "oracle", ".env"), envContent);
  fs.writeFileSync(path.join(process.cwd(), "python", "voter", ".env"), envContent);
  console.log("✅ Setup Completato! L'infrastruttura è pronta.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});