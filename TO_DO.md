# RWA & Crypto Market Intelligence MCP Agent
### Tool Reference — Build with CMC Hackathon (AI Agents & Automation Track)

This document explains the four MCP tools that make up the agent, what each one does, why it exists, and which CoinMarketCap API endpoint powers it.

---

## 1. `resolve_rwa_asset`

**Purpose:** Translates a human-readable RWA ticker or name (e.g. `GOLD`, `NVDA`, `TSLA`) into the stable internal `rwa_id` that the rest of the CMC RWA API expects.

**Why it's needed:** LLM agents and end users think in tickers, not internal IDs. Every other RWA call downstream needs the resolved ID, so this tool is the entry point of the pipeline — nothing else works without it running first.

**Endpoint:** `GET /v5/real-world-assets/map`

**Typical flow:**
1. Agent receives a natural-language request ("how is tokenized gold doing?").
2. Tool calls the `map` endpoint, searches/filters the returned list for a matching symbol or name.
3. Returns `{ rwa_id, name, symbol }` for use by other tools.

**Notes for implementation:**
- Cache the map response locally (it changes infrequently) to avoid hitting rate limits on every lookup.
- Handle ambiguous matches (multiple assets sharing a symbol) by returning candidates rather than guessing.

---

## 2. `get_rwa_market_quote`

**Purpose:** Fetches the current aggregate market data for a tokenized real-world asset — price, market cap, and 24h trading volume.

**Why it's needed:** This is the core "price check" tool. Once an asset is resolved to an `rwa_id`, this is what actually answers "what's it worth right now."

**Endpoint:** `GET /v5/real-world-assets/quotes/latest`

**Typical flow:**
1. Takes one or more `rwa_id`s (from `resolve_rwa_asset`).
2. Calls the quotes endpoint.
3. Returns structured quote data: price, market cap, 24h volume, % change.

**Notes for implementation:**
- Support batching multiple `rwa_id`s in a single call to reduce API usage.
- Normalize the response into a consistent schema so the LLM can reason over it easily (e.g., always return numeric floats, not strings).

---

## 3. `compare_rwa_vs_crypto`

**Purpose:** Runs a side-by-side comparison between a tokenized RWA and a native crypto asset (e.g., tokenized gold vs. Bitcoin, tokenized Treasuries vs. Ethereum) using price, market cap, and volume.

**Why it's needed:** This is the "interesting use of the API" differentiator for the track — it's not just displaying one dataset, it's synthesizing two different CMC product lines (RWA + crypto) into a single comparative view, which is exactly the kind of thing an AI agent is good at narrating.

**Endpoints (called concurrently):**
- `GET /v5/real-world-assets/quotes/latest`
- `GET /v3/cryptocurrency/quotes/latest`

**Typical flow:**
1. Resolve both assets (RWA via `resolve_rwa_asset`, crypto via its own symbol/ID lookup).
2. Fire both quote requests concurrently (async) to minimize latency.
3. Merge results into one comparison object: price, market cap, 24h volume, and relative performance for each side.

**Notes for implementation:**
- Use `asyncio.gather` (or equivalent) so the two API calls run in parallel rather than sequentially.
- Handle partial failure gracefully — if the crypto call fails but the RWA call succeeds, return what you have with a clear error flag rather than failing the whole tool.

---

## 4. `get_global_market_metrics`

**Purpose:** Provides macro context for the crypto market as a whole — total market cap, total 24h volume, and BTC/ETH dominance percentages.

**Why it's needed:** Individual asset quotes lack context. Knowing "BTC dominance is 54%" or "total market cap is up 3% today" lets the agent frame any single-asset answer within the broader market narrative — useful for research-assistant-style use cases.

**Endpoint:** `GET /v1/global-metrics/quotes/latest`

**Typical flow:**
1. No input parameters needed — this is a global snapshot call.
2. Returns total market cap, total volume, BTC dominance, ETH dominance, and their recent % changes.
3. Agent can reference this alongside any other tool's output for framing ("gold-backed tokens are flat, while overall crypto market cap is down 2% today").

**Notes for implementation:**
- This is a lightweight, cacheable call (e.g., refresh every few minutes) since global metrics don't need per-request freshness.
- Good candidate for a scheduled/background refresh rather than calling it on every single user query.

---

## How the Tools Work Together

```
User query ("compare tokenized gold to BTC, and how's the market overall?")
        │
        ▼
resolve_rwa_asset("GOLD")  ──►  rwa_id
        │
        ▼
compare_rwa_vs_crypto(rwa_id, "BTC")  ──►  side-by-side quote
        │
        ▼
get_global_market_metrics()  ──►  macro context
        │
        ▼
Agent synthesizes a single natural-language answer
```

`get_rwa_market_quote` sits alongside `compare_rwa_vs_crypto` as the simpler, single-asset version — used when the user only wants one RWA's numbers without a crypto comparison.

---

## Submission Checklist Reminder
- [ ] Public repo with all 4 tools implemented
- [ ] Working demo (deployed link or screen recording)
- [ ] Endpoints named explicitly (done above)
- [ ] Evidence of a real API call (code + response) for each endpoint
- [ ] Note on where the API helped / got in the way
- [ ] Track selected: **AI Agents and Automation**
- [ ] X/Twitter post with #BuildwithCMC + DoraHacks submission link