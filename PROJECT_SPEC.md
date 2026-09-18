# PROJECT_SPEC.md — RWA & Crypto Market Intelligence MCP Server
**Hackathon:** Build with CMC: API Hackathon (DoraHacks 2026)
**Track:** AI Agents and Automation / Real World Assets (RWAs)
**Target:** Top 3 Winner Grant ($10K Prize Pool & 1-Year Pro-API Access)

---

## 1. Executive Summary & Objective
This repository implements a production-grade Model Context Protocol (MCP) server that empowers LLMs (Claude Desktop, Cursor, AI Workflows) to analyze live Real-World Asset (RWA) data alongside broad crypto market metrics using the official CoinMarketCap Pro API.

The server bridges traditional finance (tokenized gold, treasuries, equities, commodities) and crypto market intelligence, giving LLMs native tools to query, compare, and summarize multi-asset financial data without requiring a web frontend.

---

## 2. Target CoinMarketCap API Endpoints
To satisfy judging criteria for API depth, code quality, and interesting use cases, the server integrates these exact CMC Pro endpoints:

1. `/v5/real-world-assets/map` — Resolves tickers/symbols (e.g., `NVDA`, `GOLD`, `SPCX`) into stable `rwa_id` identifiers.
2. `/v5/real-world-assets/quotes/latest` — Fetches tokenized aggregate market prices, tokenized market cap, and 24h volume across underlying tokens.
3. `/v5/real-world-assets/issuers/list` — Lists official token issuers (e.g., Backed Assets, Backpack) and token counts.
4. `/v3/cryptocurrency/quotes/latest` — Queries live price quotes and 24h performance for core cryptocurrencies.
5. `/v1/global-metrics/quotes/latest` — Retrieves global market indicators (BTC dominance, overall market cap, Fear & Greed signals).

---

## 3. Tool Architecture for AI Coding Agents
Code Editor Agents must implement and expose the following MCP Tools via standard JSON-RPC stdout interface:

* `resolve_rwa_asset`: Accepts symbol/ticker and returns stable `rwa_id`, asset type, and token availability.
* `get_rwa_market_quote`: Accepts `rwa_id` or `symbol` and returns aggregated tokenized price, market cap, and volume.
* `compare_rwa_vs_crypto`: Takes an RWA symbol (e.g., `GOLD`) and a Crypto symbol (e.g., `BTC`), returning normalized performance metrics and correlation context.
* `get_rwa_issuers_info`: Returns verified token issuers and token availability metrics.
* `get_market_overview`: Fetches overall market dominance, top crypto listings, and total market capitalization metrics.

---

## 4. Submission & Verification Checklist (DoraHacks Criteria)
To guarantee a valid submission before deadline:

- [ ] **Public Repository:** Public GitHub/GitLab repository containing this specification and full source code.
- [ ] **Visible API Call Evidence:** Terminal logs must output HTTP request/response metrics verifying real calls to `pro-api.coinmarketcap.com` using header `X-CMC_PRO_API_KEY`.
- [ ] **Screen Recording Demo:** 2–3 minute video showing Claude Desktop / Cursor executing MCP tools in real-time.
- [ ] **Twitter / X Post:** Post video link with hashtag `#BuildwithCMC` and DoraHacks submission link.
- [ ] **API Feedback Note:** Document response latencies, developer ergonomics, and rate limits in `API_FEEDBACK.md`.

---

## 5. Coding Agent Instructions
* **Runtime:** Node.js (v18+) TypeScript ES Modules (`"type": "module"`).
* **SDK:** `@modelcontextprotocol/sdk`.
* **API Key Handling:** Load `CMC_API_KEY` exclusively from `process.env`. Never hardcode keys into git commits.
* **Error Handling:** Gracefully handle CMC API status codes (400 invalid parameters, 429 rate limit exceeded, 500 server errors) and return human-readable text to the LLM agent.