# CMC Real-World Asset Intelligence — MCP Server

**Track:** AI Agents and Automation
**Event:** Build with CMC — CoinMarketCap API Hackathon

An MCP (Model Context Protocol) server that gives any MCP-compatible LLM
client live tools for tokenized Real-World Assets (RWAs) — gold, treasuries,
equities, and more — and lets an agent compare them directly against
cryptocurrencies, all backed by the CoinMarketCap Pro API.

## Why this exists

CoinMarketCap now tracks tokenized RWAs alongside crypto, but that data is
locked behind raw API calls most people never make. This server puts it in
front of an LLM as tools, so an agent (or you, via the included demo UI) can
ask things like *"Is tokenized gold under- or overvalued relative to
Bitcoin's market cap right now?"* and get a live, sourced answer — not a
guess from training data.

## Tools

| Tool | Purpose |
|---|---|
| `resolve_rwa_asset` | Resolve a ticker (e.g. `PAXG`) to its canonical parent RWA (`GOLD`) and its `rwa_id` |
| `get_rwa_market_quote` | Price, market cap, volume, and token breakdown for one RWA |
| `compare_rwa_vs_crypto` | Side-by-side RWA vs. cryptocurrency comparison, incl. market-cap ratio |
| `get_rwa_issuers_info` | List registered RWA token issuers and how many tokens each manages |
| `get_global_market_metrics` | BTC/ETH dominance, total market cap, 24h volume |

Every tool talks to the live CoinMarketCap Pro API — nothing is mocked.

## What makes this more than an API wrapper

- **Client-side rate limiting** — an async sliding-window limiter throttles
  outbound calls to stay under the plan's requests-per-minute ceiling, so
  the server queues gracefully instead of hammering the API into 429s.
- **Retry with backoff** — transient failures (429, 5xx, network errors) are
  retried with exponential backoff; 4xx client errors fail fast since
  retrying them can't help.
- **TTL caching** — RWA quotes, issuer lists, and global metrics are cached
  per-endpoint (30s–5min depending on how fast the data actually changes) to
  cut redundant API usage.
- **A shared, indexed symbol resolver** — resolving a token ticker (e.g.
  `PAXG`) to its parent RWA (`GOLD`) requires scanning every issuer and every
  issuer's tokens. That index is built once, cached, and reused across all
  symbol lookups instead of re-scanning per request.
- **Typed error handling** — CMC's HTTP status codes are mapped to specific
  exception types (`CMCBadRequestError`, `CMCUnauthorizedError`,
  `CMCRateLimitError`, `CMCNotFoundError`) instead of leaking raw HTTP
  errors or crashing a tool call.
- **Defensive response normalization** — CoinMarketCap's endpoints return
  inconsistent shapes for the same field (a dict in one case, a list in
  another). The Pydantic schemas and tool logic normalize these shapes
  before an agent ever sees them.
- **Domain-aware price handling** — gold-backed tokens are quoted per-gram
  by some issuers and per-troy-ounce by others; `get_rwa_market_quote`
  detects which convention a token uses and normalizes it so prices are
  actually comparable.
- **Secret-safe structured logging** — every outbound API call is logged
  with latency, status, and credit usage to stderr (never stdout, which
  would corrupt the MCP stdio stream), with API keys automatically redacted.
- **Per-request authentication** — each MCP request supplies its own
  `X-CMC_PRO_API_KEY` header, verified and rate-limited independently, so
  the server can serve multiple users/keys safely.

## Project layout

```
app/
  server.py           # FastMCP server — defines and exposes the 5 MCP tools
  config.py            # Pydantic settings, loaded from .env
  auth/
    auth.py            # Per-request API key extraction, verification, rate limiting
  cmc/
    client.py           # Async CMC API client (caching, retries, rate limiting)
    schemas.py           # Pydantic response models + shape-normalization logic
    exceptions.py         # Typed exception hierarchy mapped to CMC HTTP errors
  tools/
    resolve_rwa_asset.py     # Symbol -> parent RWA resolution (indexed + cached)
    get_rwa_market_quote.py   # Single-asset quote + gold unit normalization
    compare_rwa_vs_crypto.py   # Dual-pipeline RWA vs crypto comparison
    get_rwa_issuers_info.py     # Issuer list
    get_global_market_metrics.py # Macro crypto indicators
    registry.py                   # Central export list of all tools
  utils/
    cache.py             # TTLCache + AsyncRateLimiter (shared primitives)
    logging.py            # Structured, secret-redacting logger
  requirements.txt
  .env.example
tests/
  agent.py              # LangGraph ReAct agent wired to the MCP server (HTTP transport)
  full_test.py            # Automated end-to-end diagnostic test suite (CI-friendly, exit code 0/1)
  test_rwa_resolution.py   # Focused tests for the resolver
  streamlit_app.py          # Chat UI demo on top of tests/agent.py
  README_STREAMLIT.md        # Demo UI setup notes
  requirements.txt
```

## Setup

From the project root (the parent of `app/` and `tests/`):

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r app/requirements.txt
pip install -r tests/requirements.txt   # only needed to run the agent/demo

copy app\.env.example .env      # Windows
# cp app/.env.example .env      # macOS/Linux
```

Edit `.env` and set:
- `CMC_API_KEY` — your CoinMarketCap key (Startup tier from hackathon signup)
- `OPENAI_API_KEY` — only needed to run the demo agent/Streamlit UI

## Run the MCP server

```bash
python -m app.server
```

Starts a streamable-HTTP MCP server on `http://127.0.0.1:8000/mcp`.
Point any MCP-compatible client at that URL, or use the demo agent below.

## Run the demo agent (evidence of live API calls)

With the server running in one terminal:

```bash
python tests/agent.py
```

Runs a LangGraph ReAct agent through 5 real queries against all 5 tools,
printing each tool call and the live CMC response — this is the "visible
evidence of a real API call" artifact for the submission.

## Run the chat demo UI

```bash
streamlit run tests/streamlit_app.py
```

A browser chat UI over the same agent. Expand **"Tool calls & raw API
responses"** under any answer to see exactly which tool was called and the
raw JSON it returned. See `tests/README_STREAMLIT.md` for troubleshooting.

## Run the automated test suite

```bash
python tests/full_test.py
```

CI-friendly diagnostic suite (exit code `0`/`1`) that drives the agent
through defined scenarios and checks tool selection + expected keywords in
the response.

## Known limitations

- A handful of institutional tickers (`BUIDL`, `OUSG`, `USDY`) are not
  currently indexed by CMC's RWA endpoints under those symbols, so
  `get_rwa_market_quote` returns an honest "not tracked" response rather
  than a false match — see `RWA_SYMBOL_ALIASES` in
  `app/tools/get_rwa_market_quote.py` if/when a verified alias is found.
- All caching and rate limiting is in-memory and process-local — correct
  for a single-process hackathon deployment, not yet horizontally scaled.
