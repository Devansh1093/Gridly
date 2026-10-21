# Gridly — P2P Energy Trading

Gridly is a public demo of peer-to-peer electricity trading. It helps communities compare energy listings using an explainable, deterministic matcher that considers price, quantity, and estimated carbon intensity.

## Try the public demo

- **App:** [gridly-beta-eosin.vercel.app](https://gridly-beta-eosin.vercel.app/)
- **API health:** [gridly-ydgb.onrender.com/api/v1/health](https://gridly-ydgb.onrender.com/api/v1/health)
- Choose a scenario (sunny day, low generation, or demand spike), browse listings, and explore match previews.

The public app uses labelled simulated fixtures. Carbon and emissions figures are estimates, not measurements. The demo does not verify physical electricity delivery or transfer real funds. The API is live, but `chain_configured` is currently `false`; public wallet submission and on-chain trade recording are not enabled. Please do not interpret a match preview as a completed trade.

Render's free service may take a little time to wake after inactivity. The hosted database is for this demo and should not be treated as long-term storage.

## How it works

- **Frontend:** React, TypeScript, and Vite, hosted on Vercel.
- **API:** FastAPI and SQLAlchemy, hosted on Render with PostgreSQL.
- **Matching:** fixed, versioned scoring supports carbon-aware and price-only comparisons, with explicit factor sources and assumptions.
- **Smart contract:** Solidity trade registry with a local Hardhat development workflow. Public chain integration is not currently configured.

The API loads deterministic seed data when its database is empty. Listings are isolated by scenario. Matching previews are read-only; estimated emissions comparisons use the documented regional baseline and factor basis. An on-chain record, when enabled in a configured environment, records submitted trade data and does not prove physical delivery.

## Data and assumptions

Carbon factors are demo fixtures, not a live carbon-data feed. The Turkish grid factor is 414.2 gCO₂/kWh (IEA 2025 edition, as republished by ABB; declared data year 2023). IPCC lifecycle figures are informational and are kept separate from combustion-based comparisons. Check the cited source and assumptions before using these factors outside the demo.

## Source code

The repository includes the frontend, API, contract, deployment configuration, and detailed design notes in `docs/`. Local development and contract deployment instructions are in the project documentation.

## Public deployment configuration

The live frontend is configured with `VITE_API_BASE_URL` pointing to the Render API. Render's `FRONTEND_ORIGINS` must include the exact Vercel production origin. For another deployment, configure these values in the hosting dashboards and redeploy the frontend after changing its Vite variable; Vite embeds it during the build. Never place private keys or API credentials in the frontend or source control.
