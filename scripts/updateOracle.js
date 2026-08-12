const hre = require("hardhat");

// Usage: node scripts/updateOracle.js <oracleAddress> <btcAddress> <balanceSats> <feeWei>
// Example: node scripts/updateOracle.js 0xOracleAddress tb1qexample 100000000000 1000000000000000

async function main() {
  const [, , oracleAddr, btcAddress, balanceSatsArg, feeWeiArg] = process.argv;
  if (!oracleAddr || !btcAddress || !balanceSatsArg || !feeWeiArg) {
    console.error("Usage: node scripts/updateOracle.js <oracleAddress> <btcAddress> <balanceSats> <feeWei>");
    process.exit(1);
  }

  const balanceSats = BigInt(balanceSatsArg);
  const feeWei = hre.ethers.parseEther("0");

  // If fee passed as raw wei number, try to parse as BigInt
  const fee = BigInt(feeWeiArg);

  const [signer] = await hre.ethers.getSigners();
  const Oracle = await hre.ethers.getContractFactory("BitcoinOracle");
  const oracle = Oracle.attach(oracleAddr).connect(signer);

  const tx = await oracle.updateBalance(btcAddress, balanceSats, { value: fee });
  console.log("Submitted updateBalance tx:", tx.hash);
  const r = await tx.wait();
  console.log("Oracle updated in block", r.blockNumber);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
