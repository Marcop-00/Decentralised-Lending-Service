require("dotenv").config();

const { ethers } = require("ethers");

const rpcUrl = process.env.LOCAL_RPC_URL || "http://127.0.0.1:8545";
const funderKey = process.env.FUNDER_PRIVATE_KEY;

function parseArgs() {
  const [, , to, amountEth] = process.argv;

  if (!to || !amountEth) {
    throw new Error("Usage: npm run fund:account -- <recipientAddress> <amountEth>");
  }

  if (!ethers.isAddress(to)) {
    throw new Error(`Invalid recipient address: ${to}`);
  }

  const value = ethers.parseEther(amountEth);
  if (value <= 0n) {
    throw new Error("Transfer amount must be greater than zero.");
  }

  return { to, value };
}

async function main() {
  if (!funderKey) {
    throw new Error("FUNDER_PRIVATE_KEY is missing in environment variables.");
  }

  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const wallet = new ethers.Wallet(
    funderKey.startsWith("0x") ? funderKey : `0x${funderKey}`,
    provider,
  );

  const { to, value } = parseArgs();

  const tx = await wallet.sendTransaction({
    to,
    value,
    data: "0x",
  });

  console.log(`Transfer submitted: ${tx.hash}`);
  const receipt = await tx.wait();
  console.log(`Transfer confirmed in block ${receipt.blockNumber}`);
}

main().catch((error) => {
  console.error(`Funding failed: ${error.message}`);
  process.exit(1);
});
