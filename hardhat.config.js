require("dotenv").config();

const {
  LOCAL_RPC_URL = "http://127.0.0.1:8545",
  LOCAL_CHAIN_ID,
  DEPLOYER_PRIVATE_KEY,
  FUNDER_PRIVATE_KEY,
} = process.env;

function withHexPrefix(key) {
  if (!key) return undefined;
  return key.startsWith("0x") ? key : `0x${key}`;
}

const deployerKey = withHexPrefix(DEPLOYER_PRIVATE_KEY);
const funderKey = withHexPrefix(FUNDER_PRIVATE_KEY);
const chainId = LOCAL_CHAIN_ID ? Number(LOCAL_CHAIN_ID) : undefined;

/** @type import("hardhat/config").HardhatUserConfig */
module.exports = {
  solidity: "0.8.24",
  networks: {
    localGenesis: {
      url: LOCAL_RPC_URL,
      ...(chainId ? { chainId } : {}),
      // Use deployer key for contract deployments and contract interactions.
      // Keep prefunded account only in funding scripts.
      accounts: deployerKey ? [deployerKey] : [],
    },
    localFunder: {
      url: LOCAL_RPC_URL,
      ...(chainId ? { chainId } : {}),
      // Dedicated network alias for the prefunded account, only for value transfers.
      accounts: funderKey ? [funderKey] : [],
    },
  },
};
