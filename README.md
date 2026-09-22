# CMC Real-World Asset Intelligence — MCP Server

**Track:** AI Agents and Automation  
**Event:** Build with CMC — CoinMarketCap API Hackathon

A production-oriented MCP server for live Real-World Asset (RWA) and crypto intelligence, built to let AI clients query CoinMarketCap data through structured, auditable tool calls.

## Live deployed MCP server

The public remote endpoint is live and ready for MCP-compatible clients:

- **MCP endpoint:** `https://cmcserver.fastmcp.app/mcp`
- **Health endpoint:** `https://cmcserver.fastmcp.app/`
- **Auth header:** `X-CMC_PRO_API_KEY`

> **Security note:** API keys are supplied per-request via the `X-CMC_PRO_API_KEY` header and are never committed to this repository or persisted server-side. See `app/auth/auth.py` for key validation and rate-limiting, and `app/utils/logging.py` for secret redaction in logs.


This service is designed to be consumed by Claude Desktop, Cursor, LangGraph agents, and custom Python clients using HTTP/SSE transport.

For full deployment and connection guidance, see:

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [docs/MCP_CONNECTION.md](docs/MCP_CONNECTION.md)
- [docs/architecture.md](docs/architecture.md)

## Why this exists

CoinMarketCap tracks tokenized RWAs and crypto assets in a way that is difficult for most LLMs to access directly. This project exposes those market signals as MCP tools so an agent can reason over them in a structured and explainable way.

Examples of supported institutional-style queries:

- "Resolve `PAXG` to its parent RWA." 
- "Compare `PAXG` versus `BTC` by live market cap and volume." 
- "Rank tokenized gold issuers and output their issuer metadata." 
- "Compute the tokenized gold market penetration against the global crypto market cap."

---

## Tool capability overview

| Tool | Purpose | Key Inputs |
|---|---|---|
| `resolve_rwa_asset` | Resolve a token or RWA symbol to the parent asset and canonical `rwa_id` | `symbol` |
| `get_rwa_market_quote` | Fetch price, market cap, volume, and token metadata for an asset | `identifier` |
| `compare_rwa_vs_crypto` | Compare an RWA or tokenized RWA against a crypto asset | `rwa_symbol`, `crypto_symbol` |
| `get_rwa_issuers_info` | Return issuer metadata and token inventory | `limit`, `start` |
| `get_global_market_metrics` | Return aggregate crypto macro metrics and dominance | none |

## Resolution pathway documentation

The resolution flow is intentionally documented as a two-tier fallback system:

1. **Direct symbol lookup** — try the requested symbol first against CMC's RWA quote endpoint.
2. **Secondary token scan** — if the direct symbol does not resolve, walk issuer registries and search token metadata for the symbol, then map it back to the parent `rwa_id`.

This prevents a symbol like `PAXG` or `XAUt` from failing silently when it is a tokenized representation of a parent asset such as `GOLD`.

### Example resolution flow

```python
resolved = await resolve_rwa_asset("PAXG", api_key=api_key)
```

### Example JSON response

```json
{
  "rwa_id": 1,
  "name": "Gold",
  "symbol": "GOLD",
  "slug": "gold",
  "asset_type": "commodity",
  "rwa_rank": 1,
  "has_tokens": true,
  "resolved_via": "token_symbol",
  "matched_token": {
    "symbol": "PAXG",
    "name": "PAX Gold",
    "issuer_id": "issuer-1",
    "issuer_name": "PAX",
    "crypto_id": "gold",
    "rwa_id": 1
  }
}
```

This demonstrates the supported behavior: **`PAXG` resolves to parent asset `GOLD` with `rwa_id = 1`**.

The `matched_token` metadata includes the newly supported fields:

- **`issuer_id`**
- **`issuer_name`**
- **`crypto_id`**

---

## Cross-asset comparison engine

The comparison engine uses a normalized dual-pipeline flow and exposes an explicit `is_specific_token` flag so the caller can distinguish between aggregate RWA assets and specific tokenized securities.

### Formula: volume-to-market-cap ratio

$$
\frac{V}{MC} = \frac{\text{24h Volume (USD)}}{\text{Market Capitalization (USD)}}
$$

This metric is used to contextualize liquidity relative to asset size.

### `is_specific_token` semantics

- **`true`** when the request resolves to a specific token like `PAXG` or `XAUt`
- **`false`** when the comparison is made against the aggregate parent asset like `GOLD`

### Example: specific token comparison

```json
{
  "comparison_summary": "BTC market cap is 4.72x the size of PAXG (Gold).",
  "rwa_asset": {
    "symbol": "GOLD",
    "name": "Gold",
    "price_usd": 3031.2,
    "market_cap_usd": 15000000000,
    "volume_24h_usd": 520000000,
    "is_specific_token": true
  },
  "crypto_asset": {
    "symbol": "BTC",
    "name": "Bitcoin",
    "price_usd": 60000.0,
    "market_cap_usd": 1200000000000,
    "volume_24h_usd": 50000000000,
    "percent_change_24h": 2.5
  },
  "metrics": {
    "market_cap_ratio_crypto_to_rwa": 4.72,
    "volume_to_market_cap_ratio_rwa": 0.035,
    "volume_to_market_cap_ratio_crypto": 0.042
  }
}
```

### Example: aggregate asset comparison

```json
{
  "comparison_summary": "BTC market cap is 1.32x the size of Gold (tokenized aggregate).",
  "rwa_asset": {
    "symbol": "GOLD",
    "name": "Gold",
    "price_usd": 3051.25,
    "market_cap_usd": 190000000000,
    "volume_24h_usd": 5200000000,
    "is_specific_token": false
  },
  "crypto_asset": {
    "symbol": "BTC",
    "name": "Bitcoin",
    "price_usd": 60000.0,
    "market_cap_usd": 1200000000000,
    "volume_24h_usd": 50000000000,
    "percent_change_24h": 2.5
  },
  "metrics": {
    "market_cap_ratio_crypto_to_rwa": 1.32
  }
}
```

### 24h delta specification

The comparison payload includes the standard crypto percentage move field:

- **`percent_change_24h`** — the 24-hour percentage change for the crypto asset, expressed as a numeric percent value such as `2.5` for +2.5%.

This is included alongside the RWA market metrics to give an agent an apples-to-apples comparison context.

---

## Institutional risk & compliance schema

The RWA issuer metadata is designed to align with institutional expectations around asset provenance, reserving, custody, and supervision.

### Supported attestation and issuer metadata

The issuer registry can surface metadata such as:

- **`issuer_id`** — internal CMC issuer identifier
- **`issuer_name`** — issuer or platform name
- **`token_count`** — number of tokens associated with the issuer
- **`jurisdiction`** — operating territory or registry context
- **`custody_structure`** — physical custody arrangement or trust structure
- **`reserve_attestation`** — monthly or periodic reserve confirmation status
- **`regulatory_framework`** — NYDFS, SEC, or other relevant legal framework context

### Institutional compliance contexts

The system acknowledges the following institutional considerations:

- **NYDFS registration** for relevant regulated digital asset issuers
- **Monthly independent reserve attestations** verifying backing and reserve sufficiency
- **Physical custody structures** for commodity-backed and treasury-backed assets
- **Open transparency around asset backing, reserve controls, and reporting cadence**

These fields are not meant to replace legal or audit review, but they help standardize the metadata layer that an LLM needs when comparing regulated RWA products.

---

## Macro penetration metrics

The macro toolset supports RWA sector analysis relative to the global crypto market.

### Formula: tokenized gold sector penetration

$$
\text{Tokenized Gold Sector Penetration (\%)} = \left(\frac{\text{Total Tokenized Gold Market Cap}}{\text{Total Crypto Market Cap}}\right) \times 100
$$

This allows an agent to answer questions such as:

- "What percentage of the crypto market is represented by tokenized gold?"
- "How much of the market cap is linked to tokenized commodity exposure?"
- "Is the RWA share materially growing or still marginal?"

---

## Standardized error handling

All tools are designed to return explicit error payloads instead of crashing or returning null-only responses.

### Error shape

```json
{
  "error": "Asset with symbol 'XYZ' not found.",
  "error_hint": "Try using the parent asset symbol or check the issuer registry for a tokenized alias."
}
```

### Error handling guidance

| Error condition | Example response shape | Suggested fallback |
|---|---|---|
| Symbol not found | `{"error": "Asset with symbol 'XYZ' not found.", "error_hint": "Try parent symbol or issuer registry"}` | Try `GOLD`, `PAXG`, or issuer scan |
| Unsupported alias | `{"error": "Ticker not tracked.", "error_hint": "Check supported identifiers"}` | Use a supported parent asset or issuer list |
| Upstream API failure | `{"error": "CMC request failed.", "error_hint": "Retry after backoff or validate API credentials"}` | Retry and verify `CMC_API_KEY` |
| Invalid parameter format | `{"error": "Invalid symbol input.", "error_hint": "Use a valid 2-64 character symbol"}` | Reformat the input to valid schema |

---

## Live connection guide

To connect to the deployed server, use the following remote endpoint:

```text
https://cmcserver.fastmcp.app/mcp
```

And pass the required header:

```http
X-CMC_PRO_API_KEY: your_coinmarketcap_api_key_here
```

### Claude Desktop example

```json
{
  "mcpServers": {
    "coinmarketcap": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://cmcserver.fastmcp.app/mcp",
        "--header",
        "X-CMC_PRO_API_KEY:${CMC_API_KEY}"
      ],
      "env": {
        "CMC_API_KEY": "your_coinmarketcap_api_key_here"
      }
    }
  }
}
```

### Python example

```python
import asyncio
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

SERVER_URL = "https://cmcserver.fastmcp.app/mcp"
API_KEY = "your_coinmarketcap_api_key_here"

async def main():
    async with sse_client(SERVER_URL, headers={"X-CMC_PRO_API_KEY": API_KEY}) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            print(await session.list_tools())

asyncio.run(main())
```

---

## Setup and local execution

### Install dependencies

```bash
pip install -r requirements.txt
```

### Start the local server

```bash
python -m app.server
```

### Run the test suite

```bash
pytest .
```

---

## Documentation references

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [docs/MCP_CONNECTION.md](docs/MCP_CONNECTION.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/README_STREAMLIT.md](docs/README_STREAMLIT.md)

This documentation reflects the upgraded MCP capability set and the currently supported resolution and comparison semantics described by the live server implementation.
