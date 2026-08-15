import "@nomicfoundation/hardhat-ethers";
import "@nomicfoundation/hardhat-chai-matchers";

/** @type import("hardhat/config").HardhatUserConfig */
export default {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200
      }
    }
  },
  networks: {
    // Default network for when we run the private Geth node
    localhost: {
      url: "http://127.0.0.1:8545",
      chainId: 202526, // The chainId requested by the professor's trace
      timeout: 120000 // Timeout alzato perché Geth mina un blocco ogni 10 secondi
    }
  }
};