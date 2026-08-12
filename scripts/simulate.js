import hre from "hardhat";

async function main() {
  const { ethers } = hre;
  
  // Prendiamo il terzo account per fare da richiedente (Borrower)
  const [deployer, contributor, borrower] = await ethers.getSigners();

  // Indirizzi estratti dai tuoi log
  const POOL_ADDRESS = "0xdc64a140aa3e981100a9beca4e685f962f0cf6c9";
  const ORACLE_ADDRESS = "0xcf7ed3acca5a467e9e704c703e8d87f634fb0fc9";

  const pool = await ethers.getContractAt("FundingPool", POOL_ADDRESS);
  const oracle = await ethers.getContractAt("BitcoinOracle", ORACLE_ADDRESS);

  const btcAddress = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"; // L'indirizzo di Satoshi

  console.log("1. Il Borrower sta creando una proposta di prestito (1 ETH al 5%)...");
  const tx1 = await pool.connect(borrower).createLoanProposal(
    borrower.address,
    btcAddress,
    ethers.parseEther("1"), // 1 ETH
    500, // 5% di interesse (maggiore di 400, quindi l'auto-voter dirà di SI)
    3600, // Durata
    12 // Periodo di voto
  );
  await tx1.wait();
  console.log("✅ Proposta creata! Guarda il terminale dell'Auto-Voter!");

  console.log("\n2. Il Borrower sta richiedendo l'aggiornamento del saldo all'oracolo...");
  const minFee = await oracle.minFee();
  const tx2 = await oracle.connect(borrower).requestUpdate(btcAddress, { value: minFee });
  await tx2.wait();
  console.log("✅ Richiesta inviata! Guarda il terminale dell'Oracolo!");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});