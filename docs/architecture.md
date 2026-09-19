# Architecture

How the CMC Real-World Asset Intelligence MCP server is put together, and
why it's shaped this way. Written to be readable top-to-bottom without
needing to jump between files first.

---

## 1. The big picture

```
                    ┌─────────────────────────┐
                    │   MCP Client             │
                    │  (Claude Desktop, or the │
                    │   LangGraph demo agent)  │
                    └────────────┬─────────────┘
                                 │  MCP protocol over
                                 │  streamable-HTTP
                                 ▼
┌───────────────────────────────────────────────────────────────┐
│  app/server.py                                                 │
│  Defines 5 MCP tools. Every call passes through auth first.    │
└──────────────────┬──────────────────────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │  app/auth/auth.py      │   ← who is calling, are they
        │  (per-request)          │     allowed to call right now?
        └───────────┬─────────────┘
                    │ api_key
                    ▼
        ┌───────────────────────┐
        │  app/tools/*.py         │   ← business logic:
        │  (one file per tool)     │     "what does this tool DO"
        └───────────┬─────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │  app/cmc/client.py       │   ← ONE place that actually
        │  (CMCClient)              │     talks to CoinMarketCap
        └───────────┬─────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │   CoinMarketCap Pro API  │
        └───────────────────────┘
```

Every request flows straight down this chain. Nothing skips a layer —
a tool never calls `httpx` directly, and `server.py` never talks to CMC
directly. That's on purpose: it means each layer only has one job.

---

## 2. The five layers, one at a time

### Layer 1 — `server.py` (the front door)

This is the only file that knows about MCP itself. It:

1. Creates a `FastMCP` server instance.
2. Declares 5 tools with `@mcp.tool(...)`, each with a typed, validated
   input schema (Pydantic `Field` with regex patterns, min/max length —
   e.g. an RWA symbol must be 2–64 chars of letters/digits/`_-$@`).
3. For every tool call, first runs `authenticate_and_rate_limit(headers)`
   before doing anything else.
4. Delegates the actual work to the matching function in `app/tools/`.
5. Serializes whatever the tool returns to a JSON string (MCP tools return
   text, not structured objects).

**Why put validation here and not deeper in the stack?** Because rejecting
a malformed symbol (e.g. one with SQL-injection-looking characters) should
happen at the boundary, before it ever reaches a network call or business
logic — fail fast, fail cheap.

### Layer 2 — `auth/auth.py` (the bouncer)

Runs once per incoming tool call, before any CMC traffic happens. Three
checks, in order:

1. **Extract the key** — from the `X-CMC_PRO_API_KEY` header, or a Bearer
   token as fallback.
2. **Rate limit** — a per-key sliding-window counter (`RateLimiter`). If a
   caller has made 30+ requests in the trailing 60 seconds, they're
   rejected with a `retry_after` hint instead of being queued.
3. **Verify the key is real** — a lightweight call to CMC's
   `/v1/key/info` endpoint, cached for 5 minutes so the same key isn't
   re-verified on every single tool call.

Any failure short-circuits here and returns a clean JSON error — the
request never reaches a tool or the CMC client.

**Why is this separate from `cmc/client.py`'s own rate limiter?** They
solve different problems. `auth.py`'s limiter protects *this server* from
being abused by a single caller (per-API-key fairness at the MCP
boundary). `cmc/client.py`'s limiter protects the *outbound* connection to
CoinMarketCap from exceeding the plan's global rate limit, regardless of
which caller triggered which request. Two different budgets, two limiters.

### Layer 3 — `tools/*.py` (what each tool actually does)

One file per MCP tool. This is where the domain logic lives — it knows
about RWAs, gold pricing quirks, and comparison math, but it does **not**
know about MCP, HTTP, or how CMC's API is shaped underneath. It just calls
`cmc_client.get_xxx()` and shapes the result.

| File | What it does |
|---|---|
| `resolve_rwa_asset.py` | Turns a symbol into a canonical `rwa_id`. Tries a direct RWA-symbol match first; if that fails, falls back to a shared token index (see §3 below) to find which parent RWA a *token* symbol like `PAXG` belongs to. |
| `get_rwa_market_quote.py` | Fetches one asset's price/cap/volume. Also detects whether a gold-backed token is quoted per-gram or per-troy-ounce and normalizes it, so two gold tokens are actually comparable. |
| `compare_rwa_vs_crypto.py` | Runs the RWA lookup and the crypto lookup **concurrently** (`asyncio.gather`), then merges them into one comparison payload with a market-cap ratio. |
| `get_rwa_issuers_info.py` | Lists registered token issuers, cached for 5 minutes since this list barely changes. |
| `get_global_market_metrics.py` | BTC/ETH dominance and total market cap, cached for 2 minutes. |
| `registry.py` | Just a flat list of all 5 tool functions — used by the LangChain/LangGraph demo agent to load tools without duplicating imports. |

**Why does every tool return a plain dict, and wrap its own body in
`try/except`?** So a downstream failure (CMC down, malformed data,
whatever) becomes a graceful `{"error": "..."}` JSON payload instead of an
unhandled exception that would kill the MCP tool call. An LLM agent can
read and react to `{"error": ...}`; it can't recover from a stack trace.

### Layer 4 — `cmc/` (the only code that talks to CoinMarketCap)

Three files, three jobs:

- **`client.py` — `CMCClient`**
  The single async HTTP client. Every outbound call to CMC goes through
  `_request_json()`, which:
  - Checks an in-memory TTL cache first (skips the network entirely on a
    hit).
  - Acquires a slot from the shared `AsyncRateLimiter` (waits if the
    plan's requests-per-minute budget is currently full, rather than
    firing and catching a 429).
  - Makes the HTTP call, retries on `429`/`5xx`/network errors with
    exponential backoff, and gives up after `CMC_MAX_RETRIES`.
  - Validates the response against a Pydantic schema if one is given.
  - Writes the result back into the cache before returning it.

  Five public methods (`get_rwa_quotes`, `get_rwa_issuers_list`,
  `get_rwa_issuer`, `get_crypto_quotes`, `get_global_metrics`) map 1:1 to
  the CMC endpoints this project uses. A tool never builds a URL or sets a
  header itself — it just calls one of these.

- **`schemas.py`**
  Pydantic models mirroring CMC's response shapes. The interesting part
  isn't the happy-path models — it's the `@model_validator` methods that
  **normalize inconsistent real-world API responses** before validation
  even runs. For example, `CryptoAssetData.quote` is supposed to be
  `{"USD": {...}}`, but CMC sometimes returns it as a bare list instead;
  the validator detects that and coerces it back into the expected dict
  shape first. This is defensive code written against the *actual*
  behavior of the live API, not just its documented spec.

- **`exceptions.py`**
  A small typed exception hierarchy (`CMCBadRequestError`,
  `CMCUnauthorizedError`, `CMCRateLimitError`, `CMCNotFoundError`, and the
  base `CMCApiError`), all built from the real HTTP status code. This lets
  `client.py`'s retry logic decide "retry this" (429/5xx) vs. "don't
  bother, it'll never succeed" (400/401/404) based on error *type*, not by
  re-parsing status codes everywhere.

### Layer 5 — `utils/` (shared plumbing, used by everything above)

- **`cache.py`**
  Two small, dependency-free primitives:
  - `TTLCache` — async-safe, per-key expiry, bounded size (evicts the
    oldest entry when full). Used by the CMC client and by two tools
    directly (`shared_cache` singleton for issuer info / global metrics).
  - `AsyncRateLimiter` — a sliding-window limiter used as an async context
    manager (`async with self._rate_limiter:`). Callers that would exceed
    the limit `await` inside `acquire()` until a slot frees up, instead of
    failing — this is what keeps the server well-behaved against CMC's
    limits proactively, rather than reactively catching 429s.

- **`logging.py`**
  A configured logger that writes to **stderr only** (writing to stdout
  would corrupt the MCP stdio protocol stream if the server is ever run
  over stdio transport) and automatically redacts anything that looks like
  an API key before it hits a log line — both a UUID-pattern regex and a
  denylist of header/param names (`x-cmc_pro_api_key`, `authorization`,
  etc.).

---

## 3. Two design decisions worth understanding

### Why does resolving a token symbol (e.g. `PAXG`) require a whole index?

CMC's RWA API doesn't offer a direct "look up this token symbol" endpoint.
The only way to find out that `PAXG` belongs to the parent asset `GOLD` is
to walk every registered issuer, then every issuer's token list, until you
find a token whose symbol matches.

Doing that walk **fresh on every single unresolved symbol** would mean
re-scanning the same data over and over for different callers within the
same minute. Instead, `resolve_rwa_asset.py` builds one shared index
(`token_symbol -> parent rwa_id`) by doing that walk exactly once, caches
it for 5 minutes, and every symbol lookup after that is an O(1) dict
lookup against the cached index. A lock ensures that if two requests need
the index at the same moment it hasn't been built yet, only one of them
does the actual scan — the other just waits and reuses the result.

### Why is RWA-vs-crypto comparison split into two fully separate pipelines?

`compare_rwa_vs_crypto.py` fetches the RWA side and the crypto side as two
independent functions (`fetch_rwa_data`, `fetch_crypto_data`) run
concurrently with `asyncio.gather`, and only merges them at the very end.

RWAs and standard cryptocurrencies come back from CMC in **completely
different response shapes** (aggregated tokenized-asset arrays vs.
per-symbol coin quotes). Trying to handle both inside one shared code path
would mean constant shape-branching. Keeping them isolated means each
pipeline's normalization logic only has to reason about one shape, and
running them concurrently (instead of sequentially) means a comparison
call costs roughly the time of the *slower* of the two lookups, not the
sum of both.

---

## 4. Request lifecycle, end to end

A single call to `compare_rwa_vs_crypto("GOLD", "BTC")` through the flow:

1. **MCP client** sends the tool call with `X-CMC_PRO_API_KEY` in headers.
2. **`server.py`** validates `rwa_symbol` and `crypto_symbol` against their
   Pydantic patterns/lengths.
3. **`auth.py`** extracts the key, checks the caller hasn't exceeded 30
   req/min, verifies the key against CMC (cached, so usually instant).
4. **`compare_rwa_vs_crypto()`** kicks off two concurrent branches:
   - **RWA branch:** `resolve_rwa_asset("GOLD")` → hits the shared
     resolution cache or resolves fresh → `cmc_client.get_rwa_quotes(...)`.
   - **Crypto branch:** `cmc_client.get_crypto_quotes("BTC")`.
5. Each branch's raw response is checked against the CMC TTL cache first
   inside `CMCClient._request_json`; on a miss, the rate limiter is
   acquired, the HTTP call is made (with retry/backoff if needed), the
   response is schema-validated, and the result is cached.
6. Both branches return; their results are merged into one comparison
   payload (price, market cap, volume, market-cap ratio for each side).
7. `server.py` JSON-serializes the result and returns it as the tool's
   text output.
8. Any failure at any step returns a structured `{"error": "..."}"`
   payload instead of propagating an exception up to the MCP client.

---

## 5. What's intentionally *not* here

- **No database.** All caching is in-memory, process-local, and expected
  to reset on restart — appropriate for a single-process server, not (yet)
  a horizontally scaled deployment.
- **No LLM inside the server itself.** The MCP server only exposes tools;
  the LLM reasoning happens in whatever client connects to it (Claude
  Desktop, or the LangGraph demo agent in `tests/agent.py`).
- **No alias resolution for untracked institutional tickers** (`BUIDL`,
  `OUSG`, `USDY`) — `get_rwa_market_quote.py` deliberately returns an
  honest "not currently tracked" response for these rather than silently
  guessing a proxy, since no verified mapping exists yet.
