import hardhatToolboxViem from "@nomicfoundation/hardhat-toolbox-viem";
import { defineConfig } from "hardhat/config";

export default defineConfig({
  plugins: [hardhatToolboxViem],
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: { enabled: true, runs: 200 },
      // The professor's Clique genesis activates forks only through Berlin.
      evmVersion: "berlin",
    },
  },
  networks: {
    default: {
      type: "edr-simulated",
      chainType: "l1",
      chainId: 202526,
      hardfork: "berlin",
    },
    localhost: {
      type: "http",
      chainType: "l1",
      url: "http://127.0.0.1:8545",
      chainId: 202526,
      timeout: 120000,
    },
  },
});
