import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { Wallet } from "ethers";

const envPath = resolve(import.meta.dirname, "..", ".env");
const existing = existsSync(envPath) ? readFileSync(envPath, "utf8") : "";
const values = new Map(existing.split(/\r?\n/).filter(Boolean).map((line) => {
  const splitAt = line.indexOf("=");
  return splitAt > 0 ? [line.slice(0, splitAt), line.slice(splitAt + 1)] : [line, ""];
}));
const defaults = {
  DATABASE_URL: "sqlite:///./app/backend/data/demo.sqlite3",
  API_HOST: "127.0.0.1",
  API_PORT: "8000",
  RPC_URL: "http://127.0.0.1:8545",
  CHAIN_ID: "31337",
  CONTRACT_ADDRESS: "",
  TRADE_AUTH_SIGNER_PRIVATE_KEY: Wallet.createRandom().privateKey,
  PREVIEW_TOKEN_SIGNING_KEY: randomBytes(32).toString("hex"),
  PREVIEW_TOKEN_TTL_SECONDS: "300",
  CARBON_DATA_MODE: "fixture",
  VITE_API_BASE_URL: "http://127.0.0.1:8000",
  VITE_CHAIN_ID: "31337",
  VITE_CONTRACT_ADDRESS: values.get("CONTRACT_ADDRESS") || "",
  VITE_RPC_URL: "http://127.0.0.1:8545",
};
for (const [key, value] of Object.entries(defaults)) {
  if (!values.has(key) || !values.get(key)) values.set(key, value);
}
writeFileSync(envPath, `${[...values].map(([key, value]) => `${key}=${value}`).join("\n")}\n`, { mode: 0o600 });
console.log(`Created local configuration at ${envPath}. Keep it out of source control and use it only with the local Hardhat chain.`);
