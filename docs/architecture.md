# Architecture

How the CMC Real-World Asset Intelligence MCP server is put together, and why it is shaped this way.

---

## 1. The big picture

```text
                    ┌─────────────────────────┐
                    │  MCP Client             │
                    │  (Claude Desktop,       │
                    │   Cursor, LangGraph)    │
                    └────────────┬────────────┘
                                 │  MCP over HTTP/SSE
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│ app/server.py                                                    │
│ Registers tool handlers and applies auth plus request validation │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
                   ┌─────────────────────┐
                   │ app/auth/auth.py    │
                   │ Per-request auth    │
                   │ and rate limiting   │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │ app/tools/*.py      │
                   │ Domain logic        │
                   │ resolution + quotes │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │ app/cmc/client.py   │
                   │ One outbound CMC    │
                   │ HTTP client         │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │ CoinMarketCap Pro   │
                   │ API                 │
                   └─────────────────────┘
```

---

## 2. Core design decisions

### 2.1 Resolution pathway design

The resolution system follows a clear two-tier path:

1. **Direct lookup**: try the exact requested symbol against CMC's RWA quote endpoint.
2. **Token fallback**: if the direct lookup fails, scan issuer token registries and map the token back to its parent `rwa_id`.

This is the mechanism behind `PAXG` resolving to parent asset `GOLD` and `rwa_id = 1`.

Example:

```json
{
  "rwa_id": 1,
  "symbol": "GOLD",
  "resolved_via": "token_symbol",
  "matched_token": {
    "symbol": "PAXG",
    "issuer_id": "issuer-1",
    "issuer_name": "PAX",
    "crypto_id": "gold",
    "rwa_id": 1
  }
}
```

This flow is intentionally documented because fallback resolution is a real, supported capability and should not be treated as an undocumented bug or silent miss.

### 2.2 Cross-asset comparison architecture

The comparison engine resolves and normalizes both pipelines independently before merging:

- **RWA pipeline** resolves the symbol and extracts the relevant asset metadata
- **Crypto pipeline** resolves the target crypto symbol using the standard quote endpoint
- **Merge stage** computes market cap ratios and liquidity metrics

The payload includes the boolean:

- **`is_specific_token`**: `true` when comparing a child token like `PAXG`; `false` for parent aggregate assets like `GOLD`

### 2.3 Macro market framing

The system can compute sector penetration relative to total crypto market cap, using:

$$
\text{Tokenized Gold Sector Penetration (\%)} = \left(\frac{\text{Total Tokenized Gold Market Cap}}{\text{Total Crypto Market Cap}}\right) \times 100
$$

This supports institutional-style narrative reporting and informs RWA deepness vs. broad crypto market exposure.

---

## 3. Institutional risk and compliance schema

The RWA ecosystem includes a compliance layer that matters to institutional evaluators.

### 3.1 Issuer metadata categories

The issuer registry can expose metadata such as:

| Field | Meaning |
|---|---|
| `issuer_id` | Unique issuer identifier |
| `issuer_name` | Issuer or platform name |
| `token_count` | Count of tracked child tokens |
| `custody_structure` | Where physical or legal custody is held |
| `regulatory_framework` | NYDFS, SEC, or equivalent context |
| `reserve_attestation` | Monthly or periodic attestation status |
| `jurisdiction` | Regulatory territory or compliance footprint |

### 3.2 Compliance contexts

The architecture is aligned with institutional reporting expectations:

- **NYDFS registration** awareness for regulated issuers
- **Independent reserve attestations** with regular verification cadence
- **Physical custody structures** for commodity-backed reserves
- **Asset backing disclosure** that helps explain token economics to an AI or human analyst

These metadata layers are important audit-readiness signals even when the underlying raw endpoint is a market data feed rather than a legal registry.

---

## 4. Error-handling contract

All tools are intentionally designed to return explicit, non-null structured errors rather than crashing the request.

```json
{
  "error": "Asset with symbol 'XYZ' not found.",
  "error_hint": "Try using the parent asset symbol or check the issuer registry for a tokenized alias."
}
```

### Error schema table

| Condition | Response pattern | Guidance |
|---|---|---|
| Symbol not found | `error` + `error_hint` | Retry with parent symbol or scanned issuer alias |
| API failure | `error` + `error_hint` | Validate credentials and retry after backoff |
| Invalid input | `error` + `error_hint` | Ensure formatting matches symbol constraints |
| Unsupported alias | `error` + `error_hint` | Use engine-supported identifiers or issuer registry |

---

## 5. Tooling and execution flow

### 5.1 `server.py`

The FastMCP server front door performs a single gate:

- validate schema inputs
- enforce auth headers
- delegate to tool logic
- return JSON strings to the MCP client

### 5.2 `auth/auth.py`

This layer validates the caller and rate limits requests based on the `X-CMC_PRO_API_KEY` header before any live CMC traffic occurs.

### 5.3 `cmc/client.py`

This file centralizes all requests to CoinMarketCap, with:

- TTL caching
- HTTP retries
- rate limiting
- response validation

### 5.4 `tools/*.py`

This folder contains the domain logic for:

- RWA resolution
- quote normalization
- crypto comparison
- sector penetration analysis
- issuer metadata parsing

---

## 6. Request lifecycle summary

1. The client connects via HTTP/SSE to the remote MCP endpoint.
2. The request includes `X-CMC_PRO_API_KEY`.
3. Auth and rate limiting run before the tool executes.
4. The tool resolves the requested symbol with direct-lookup + token-fallback logic.
5. The resulting data is normalized and returned as a structured JSON response.
6. The client may then convert that response to an LLM-readable narrative or run a second query.

---

### 6.1 Worked example: `compare_rwa_vs_crypto("GOLD", "BTC")`

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

## 7. What's intentionally *not* here

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

---

## 8. Test coverage

The suite is `tests/test_mcp_tools_unit.py` (13 tests) plus `tests/test_extended_coverage.py` (31 tests), 44 total.

- **`test_mcp_tools_unit.py`** covers the two-tier resolver in `resolve_rwa_asset.py` (token-symbol fallback, smallest-issuer-first scanning, registry reuse/caching, transient-failure retry), the merge logic in `compare_rwa_vs_crypto.py` (specific-token vs. aggregate framing, refusing to attach a `percent_change_24h` when `crypto_id` doesn't match, list-vs-dict payload handling), a schema regression on `RWAIssuerResponse`, and the retry-eligibility rules in `cmc/client.py` (`_is_retryable`).
- **`test_extended_coverage.py`** closes the gap that suite left: `app/utils/cache.py` (`TTLCache` TTL-boundary expiry, nearest-to-expiry eviction, `get_or_set` memoization; `AsyncRateLimiter` token-bucket waiting behavior), `app/auth/auth.py` (per-key sliding-window `RateLimiter`, independent per-key budgets, the full `authenticate_and_rate_limit` flow including 401/429 payload shapes), `get_global_market_metrics.py` (field mapping, 2-minute caching, error-dict-not-exception behavior), `get_rwa_issuers_info.py` (formatting, per-`limit` cache isolation), and the parts of `get_rwa_market_quote.py` not already reached via `compare_rwa_vs_crypto` — the gram-vs-troy-ounce unit heuristic, the 16-character fast-path rejection (no API round trip), the honest "not currently indexed" hint for known-but-untracked tickers, and numeric-identifier-as-`rwa_id` resolution.

### Remaining gaps

- **`server.py`** request validation and tool dispatch are exercised only indirectly (through `auth.py` and the tool functions directly) — nothing drives a request through the actual FastMCP boundary.
- **`config.py`** (Pydantic Settings/env loading) has no dedicated tests.
- **`utils/logging.py`** secret redaction is undocumented by tests despite being called out as a security property in the README.
- **`compare_rwa_vs_crypto`** has no test for the crypto-side lookup itself failing (e.g. an invalid `crypto_symbol`) inside the comparison flow.

---

## 9. Documentation references

- [README.md](../README.md)
- [docs/DEPLOYMENT.md](DEPLOYMENT.md)
- [docs/MCP_CONNECTION.md](MCP_CONNECTION.md)
- [docs/README_STREAMLIT.md](README_STREAMLIT.md)

This architecture is intentionally designed to be explainable, testable, and institutionally legible for evaluators and AI clients alike.
