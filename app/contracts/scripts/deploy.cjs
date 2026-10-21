const fs = require("node:fs");
const path = require("node:path");
const hre = require("hardhat");

async function main() {
  const projectRoot = path.resolve(__dirname, "../../..");
  const envPath = path.join(projectRoot, ".env");
  const privateKey = process.env.TRADE_AUTH_SIGNER_PRIVATE_KEY;
  if (!privateKey) throw new Error("TRADE_AUTH_SIGNER_PRIVATE_KEY is missing; run npm run setup:local first.");
  const [deployer] = await hre.ethers.getSigners();
  const authSigner = new hre.ethers.Wallet(privateKey).address;
  const factory = await hre.ethers.getContractFactory("EnergyTradeRegistry", deployer);
  const registry = await factory.deploy(authSigner);
  await registry.waitForDeployment();
  const address = await registry.getAddress();
  const current = fs.existsSync(envPath) ? fs.readFileSync(envPath, "utf8") : "";
  const lines = new Map(current.split(/\r?\n/).filter(Boolean).map((line) => {
    const i = line.indexOf("=");
    return i > 0 ? [line.slice(0, i), line.slice(i + 1)] : [line, ""];
  }));
  lines.set("CONTRACT_ADDRESS", address);
  lines.set("VITE_CONTRACT_ADDRESS", address);
  fs.writeFileSync(envPath, `${[...lines].map(([key, value]) => `${key}=${value}`).join("\n")}\n`, { mode: 0o600 });
  const deployPath = path.join(projectRoot, "app/contracts/deployments");
  fs.mkdirSync(deployPath, { recursive: true });
  fs.writeFileSync(path.join(deployPath, "localhost.json"), JSON.stringify({ address, chainId: Number(process.env.CHAIN_ID || 31337), authorizationSigner: authSigner }, null, 2));
  console.log(`EnergyTradeRegistry deployed at ${address}; local .env updated.`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
