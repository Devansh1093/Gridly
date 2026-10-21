# Gridly · P2P Energy Trading

Gridly is a web application for peer-to-peer electricity listings, deterministic carbon-aware matching, and an EVM audit registry. It uses fixture data and records submitted trade fields; it does not transfer funds or verify physical energy delivery.

## Architecture

- `app/frontend`: React, TypeScript, Vite, Tailwind CSS, Lucide, and ethers.js. The browser wallet submits the contract call.
- `app/backend`: FastAPI, Pydantic, SQLAlchemy, and SQLite for the local demo. It publishes listings, previews matches, reserves quantity, signs EIP-712 authorization permits, verifies chain submissions, reconciles status, and serves dashboard metrics.
- `app/contracts`: Solidity `EnergyTradeRegistry` with duplicate prevention, deadline checks, a backend authorization signer, and a complete audit event.
- `docs`: frontend, backend, and architecture requirements.

The default seed is deterministic (`seed.v1`), and all market matching uses one scenario at a time. The dashboard can explicitly aggregate completed trades across scenarios.

## Local setup

Requirements: Node.js 20+, npm, and Python 3.11+.

1. From this directory, install Node dependencies:

   ```sh
   npm install
   ```

2. Create a Python virtual environment and install the API dependencies:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r app\backend\requirements.txt
   ```

   On macOS or Linux, use `python3 -m venv .venv` and `.venv/bin/python -m pip install -r app/backend/requirements.txt`.

3. Generate local-only signing secrets and a `.env` file:

   ```sh
   npm run setup:local
   ```

   The generated private signer key is used only to authorize demo trades on the local chain. `.env` is ignored by Git. Never reuse it on a public network or with funded accounts.

4. Start a local Hardhat node in terminal 1:

   ```sh
   npm run chain
   ```

5. Deploy the registry in terminal 2:

   ```sh
   npm run deploy:local
   ```

   The command deploys to `localhost`, stores the local address in `.env`, and writes a Git-ignored deployment record. If using MetaMask, add the local Hardhat network (RPC `http://127.0.0.1:8545`, chain ID `31337`) and import one of the local accounts printed by Hardhat. Never use a real wallet key.

6. Load the demo fixtures if needed, then start the API and frontend in terminal 3:

   ```sh
   npm run seed -- --reset --scenario all
   npm run dev
   ```

   Open `http://127.0.0.1:5173`. The API is at `http://127.0.0.1:8000`; interactive API docs are at `http://127.0.0.1:8000/docs`.

If PowerShell blocks `npm.ps1`, run the same commands with `npm.cmd` (for example, `npm.cmd run dev`).

## Useful commands

```sh
npm run seed -- --reset --scenario sunny-day
npm run seed -- --reset --scenario low-generation
npm run seed -- --reset --scenario demand-spike
npm run seed -- --reset --scenario all
npm run compile:contract
npm run build
```

Seed reset clears participants, listings, requests, and trade reservations in SQLite; it never changes chain state. Redeploy the contract or restart the Hardhat node separately for a clean chain history. Seed quantities are entered in kWh and persisted as integer Wh. Prices are integer EUR cents/kWh.

## Demo behavior

- Preview is read-only and returns a bounded-lifetime signed token plus a snapshot hash. Acceptance requires an idempotency key and reserves both the sell listing and buy request in one transaction.
- Ranking uses versioned integer basis-point scoring. `price_only` uses price and quantity fit; `carbon_aware` adds the seller scenario intensity. Baseline availability only affects the emissions comparison.
- The browser signs and submits `recordTrade`. The API registers the transaction hash, checks the destination and call payload, and marks a trade `Done` only after a finalized receipt and event verification.
- `Offer` means ready for wallet submission, `Pending` means submitted and awaiting verification, `Done` means verified on chain, and `Fail` records a terminal failure. A transaction hash that is merely missing is never treated as proof of failure.
- Carbon factors show their source, basis, region and simulated-data label. The IEA/ABB TR factor uses 414.2 gCO₂/kWh (2023 data year, 2025 edition); IPCC lifecycle values remain informational and are excluded from the combustion comparison.

## Configuration

Copy `.env.example` only as a reference; `npm run setup:local` creates the usable local `.env`. `PREVIEW_TOKEN_SIGNING_KEY` and `TRADE_AUTH_SIGNER_PRIVATE_KEY` are backend-only values. Only `VITE_*` settings are exposed to the browser. The API refuses to issue previews without a sufficiently long signing key and refuses wallet preparation until a local contract and signer are configured.

No real carbon provider is connected. Carbon factors are reproducible demo fixtures; estimated emissions are estimates, and the chain event records submitted data rather than proving delivery.
