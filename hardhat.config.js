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
    // Rete di default per quando lanciamo il nodo privato di Geth
    localhost: {
      url: "http://127.0.0.1:8545",
      chainId: 202526, // Il chainId richiesto dalla traccia del prof
      timeout: 120000 // Timeout alzato perché Geth mina un blocco ogni 10 secondi
    }
  }
};