require("dotenv").config({ path: require("path").resolve(__dirname, "../..", ".env") });
require("@nomicfoundation/hardhat-ethers");

module.exports = {
  solidity: {
    version: "0.8.24",
    settings: { optimizer: { enabled: true, runs: 200 }, viaIR: true },
  },
  paths: {
    sources: "./contracts",
    tests: "./test",
    cache: "./cache",
    artifacts: "./artifacts",
  },
  networks: {
    hardhat: { chainId: 31337 },
    localhost: { url: process.env.RPC_URL || "http://127.0.0.1:8545", chainId: Number(process.env.CHAIN_ID || 31337) },
  },
};
