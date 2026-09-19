# CMC Real-World Asset Intelligence — MCP Server

**Track:** AI Agents and Automation
**Event:** Build with CMC — CoinMarketCap API Hackathon

An MCP (Model Context Protocol) server that gives any MCP-compatible LLM
client (Claude Desktop, Claude Code, etc.) live tools for tokenized
Real-World Assets (RWAs) and their comparison against cryptocurrencies,
backed by the CoinMarketCap Pro API.

## Tools

| Tool | Purpose | Endpoint |
|---|---|---|
| `resolve_rwa_asset` | Resolve a ticker/name to a canonical `rwa_id` | `GET /v5/real-world-assets/map` |
| `get_rwa_market_quote` | Price, market cap, volume for one RWA | `GET /v5/real-world-assets/quotes/latest` |
| `compare_rwa_vs_crypto` | Side-by-side RWA vs. crypto comparison | `GET /v5/real-world-assets/quotes/latest` + `GET /v3/cryptocurrency/quotes/latest` |
| `get_rwa_issuers_info` | List RWA token issuers | `GET /v5/real-world-assets/issuers/list` |
| `get_global_market_metrics` | BTC/ETH dominance, total market cap | `GET /v1/global-metrics/quotes/latest` |

See `tool_reference.md` (the design doc) for the full rationale behind each
tool and how they compose.

## Production-grade features

- **Authentication**: `X-CMC_PRO_API_KEY` header set from `CMC_API_KEY` in
  `.env`; the server refuses to start if the key is missing, and fails fast
  with a clear `CMCUnauthorizedError` if CMC rejects it (401/403) rather
  than an opaque HTTP error.
- **Client-side rate limiting**: an async token-bucket limiter
  (`app/utils/cache.py::AsyncRateLimiter`) throttles outbound calls to
  `CMC_RATE_LIMIT_PER_MINUTE` (default 30/min, matching the Startup tier)
  so the server queues instead of hammering the API into 429s.
- **Retry with backoff**: transient failures (429, 5xx, timeouts) are
  retried up to `CMC_MAX_RETRIES` times with exponential backoff + jitter;
  4xx client errors (bad request, not found) fail immediately since retrying
  them can't help.
- **Caching**: a shared in-memory TTL cache (`app/utils/cache.py::TTLCache`)
  backs the rarely-changing endpoints — global metrics (2 min) and issuer
  lists (5 min) — to cut API usage without serving stale price data.
- **Structured logging**: every outbound API call is logged to stderr
  (never stdout, which would corrupt the MCP stdio stream) with latency,
  status, and credit usage — with API keys automatically redacted.
- **Typed errors**: `app/cmc/exceptions.py` maps CMC's HTTP status codes to
  specific exception types (`CMCBadRequestError`, `CMCUnauthorizedError`,
  `CMCRateLimitError`, `CMCNotFoundError`) so callers can branch on failure
  mode instead of parsing strings.
- **Schema validation**: request parameters are validated with Pydantic
  (symbol patterns, length bounds, numeric ranges) before ever reaching the
  network.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
# edit .env and set CMC_API_KEY
```

## Run the MCP server

```bash
python -m app.server
```

Point your MCP client (e.g. Claude Desktop's `claude_desktop_config.json`)
at this command over stdio.

## Run the live demo / evidence script

```bash
python -m app.scripts.demo_query
```

Calls all 5 tools against the real CMC API and prints each request/response
— see `scripts/record_demo.md` for the full recording checklist used for
the hackathon submission.

## Project layout

```
app/
  cmc/            # CMC API client, typed exceptions, response schemas
  tools/          # One module per MCP tool (business logic, framework-agnostic)
  utils/          # Cache/rate-limiter and logging utilities shared across the app
  scripts/        # Demo/evidence script + recording runbook
  config.py       # Pydantic settings (.env-driven)
  server.py       # FastMCP server wiring tools to the MCP protocol
```
