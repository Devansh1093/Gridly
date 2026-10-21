const fs = require("node:fs");
const path = require("node:path");
const hre = require("hardhat");

async function main() {
  const projectRoot = path.resolve(__dirname, "../../..");
  const envPath = path.join(projectRoot, ".env");
  const privateKey = process.env.TRADE_AUTH_SIGNER_PRIVATE_KEY;
  if (!privateKey) throw new Error("TRADE_AUTH_SIGNER_PRIVATE_KEY is missing. Set a dedicated backend authorization signer key in your ignored .env.");
  const signers = await hre.ethers.getSigners();
  if (!signers.length) throw new Error("No deployer account is configured for this network.");
  const [deployer] = signers;
  const network = await hre.ethers.provider.getNetwork();
  const networkName = hre.network.name;
  const chainId = Number(network.chainId);
  if (networkName === "sepolia" && chainId !== 11155111) {
    throw new Error(`Expected Sepolia chain ID 11155111, connected to ${chainId}. Check SEPOLIA_RPC_URL.`);
  }
  if (networkName === "sepolia" && !process.env.SEPOLIA_DEPLOYER_PRIVATE_KEY) {
    throw new Error("SEPOLIA_DEPLOYER_PRIVATE_KEY is missing from your ignored .env.");
  }
  const authSigner = new hre.ethers.Wallet(privateKey).address;
  const factory = await hre.ethers.getContractFactory("EnergyTradeRegistry", deployer);
  const registry = await factory.deploy(authSigner);
  await registry.waitForDeployment();
  const address = await registry.getAddress();
  const deploymentTx = registry.deploymentTransaction();
  const deploymentReceipt = deploymentTx ? await deploymentTx.wait() : null;
  const current = fs.existsSync(envPath) ? fs.readFileSync(envPath, "utf8") : "";
  const lines = new Map(current.split(/\r?\n/).filter(Boolean).map((line) => {
    const i = line.indexOf("=");
    return i > 0 ? [line.slice(0, i), line.slice(i + 1)] : [line, ""];
  }));
  lines.set("CONTRACT_ADDRESS", address);
  lines.set("VITE_CONTRACT_ADDRESS", address);
  lines.set("CHAIN_ID", String(chainId));
  lines.set("VITE_CHAIN_ID", String(chainId));
  const rpcUrl = networkName === "sepolia" ? process.env.SEPOLIA_RPC_URL : (process.env.RPC_URL || "http://127.0.0.1:8545");
  if (rpcUrl) {
    lines.set("RPC_URL", rpcUrl);
    lines.set("VITE_RPC_URL", rpcUrl);
  }
  fs.writeFileSync(envPath, `${[...lines].map(([key, value]) => `${key}=${value}`).join("\n")}\n`, { mode: 0o600 });
  const deployPath = path.join(projectRoot, "app/contracts/deployments");
  fs.mkdirSync(deployPath, { recursive: true });
  fs.writeFileSync(path.join(deployPath, `${networkName}.json`), JSON.stringify({
    address,
    chainId,
    authorizationSigner: authSigner,
    deployer: await deployer.getAddress(),
    deploymentTransactionHash: deploymentReceipt?.hash || deploymentTx?.hash || null,
  }, null, 2));
  console.log(`EnergyTradeRegistry deployed to ${networkName} at ${address} (chain ${chainId}).`);
  console.log(`Deployment record: app/contracts/deployments/${networkName}.json`);
  console.log("Local .env updated. Copy the public settings to Vercel and the backend settings to Render; never publish either signer key.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
