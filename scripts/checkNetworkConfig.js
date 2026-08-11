require("dotenv").config();

const fs = require("fs");
const path = require("path");

const rpcUrl = process.env.LOCAL_RPC_URL || "http://127.0.0.1:8545";
const envChainId = process.env.LOCAL_CHAIN_ID
  ? Number(process.env.LOCAL_CHAIN_ID)
  : undefined;
const genesisPathArg = process.argv[2] || "project2526genesis.json";
const genesisPath = path.resolve(process.cwd(), genesisPathArg);

function readGenesis(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Genesis file not found at: ${filePath}`);
  }

  const raw = fs.readFileSync(filePath, "utf8");
  const parsed = JSON.parse(raw);
  const chainId = parsed?.config?.chainId;

  if (typeof chainId !== "number") {
    throw new Error(
      `Invalid genesis file at ${filePath}: config.chainId must be a number`,
    );
  }

  return chainId;
}

async function getRpcChainId(url) {
  const body = {
    jsonrpc: "2.0",
    id: 1,
    method: "eth_chainId",
    params: [],
  };

  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`RPC call failed (${response.status} ${response.statusText})`);
  }

  const data = await response.json();
  if (!data?.result || typeof data.result !== "string") {
    throw new Error(`Invalid RPC response: ${JSON.stringify(data)}`);
  }

  return Number.parseInt(data.result, 16);
}

async function main() {
  const genesisChainId = readGenesis(genesisPath);
  const rpcChainId = await getRpcChainId(rpcUrl);

  console.log(`Genesis chainId: ${genesisChainId}`);
  console.log(`RPC chainId: ${rpcChainId}`);

  if (envChainId !== undefined) {
    console.log(`Env LOCAL_CHAIN_ID: ${envChainId}`);
    if (envChainId !== genesisChainId) {
      throw new Error(
        `LOCAL_CHAIN_ID (${envChainId}) does not match genesis chainId (${genesisChainId})`,
      );
    }
  }

  if (rpcChainId !== genesisChainId) {
    throw new Error(
      `RPC chainId (${rpcChainId}) does not match genesis chainId (${genesisChainId})`,
    );
  }

  console.log("Network configuration is aligned with genesis.");
}

main().catch((error) => {
  console.error(`Network check failed: ${error.message}`);
  process.exit(1);
});
