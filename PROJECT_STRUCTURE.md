# CMC RWA Agent — Project Structure & File Roles

This document explains **what every file in the project does**, why it exists, and how it fits into the overall flow: `FastAPI (entry) → LangGraph (agent brain) → Tools (actions) → CMC Client (data) → MCP (external exposure)`.

Read this top-to-bottom once, and you'll understand the whole codebase before writing a line.

---

## Root-level files

### `README.md`
The single most important file for judges. This is **not** internal documentation — it's your pitch. Structure it as:
1. One-sentence problem statement ("Comparing tokenized RWAs against crypto requires manually checking two different data sources — this agent does it in one query.")
2. A demo GIF or video link at the top, above the fold
3. Setup/run instructions (should take under 2 minutes to follow)
4. The 4 tools and endpoints, listed explicitly (submission requirement)
5. Architecture diagram or link to `docs/architecture.md`
6. What track this targets and why

### `.env.example`
A template showing which environment variables the app needs (`CMC_API_KEY`, `OPENAI_API_KEY`, `PORT`, etc.) **without real values**. Anyone cloning the repo copies this to `.env` and fills in their own keys. This file exists specifically so you never commit a real key — judges explicitly penalize leaked keys in code quality scoring.

### `.gitignore`
Prevents `.env`, `__pycache__/`, virtual environment folders, and log files from ever being committed. Directly protects you from the "don't commit keys" rule.

### `requirements.txt`
Pins every Python dependency (`fastapi`, `langchain`, `langgraph`, `httpx`, `pydantic`, `uvicorn`, etc.) so anyone — including a judge — can recreate your exact environment with one command. Missing or vague dependencies is one of the fastest ways to lose "code quality" points because the demo simply won't run for them.

### `LICENSE`
States how others can use your code. Not scored directly, but its absence signals an unfinished/unprofessional repo. MIT is the standard, low-friction choice for hackathons.

---

## `app/` — the application package

### `app/main.py`
**The single entrypoint.** This file creates the `FastAPI()` instance, registers all routers (`routes_chat`, `routes_tools`, `routes_health`), sets up CORS/middleware if needed, and is what `uvicorn` actually runs (`uvicorn app.main:app`). Nothing else in the app should start the server — everything else is imported *by* this file, never the other way around.

### `app/config.py`
Centralizes all configuration using `pydantic-settings`. Reads environment variables once (API keys, CMC base URL, request timeout, cache TTL) and exposes them as a typed `Settings` object that every other file imports. Exists so that no file ever calls `os.getenv()` directly — one source of truth, one place to change if a key name or default changes.

---

## `app/api/` — FastAPI route layer (the "front door")

This layer's only job is to **translate HTTP requests into function calls** and **translate function results back into HTTP responses**. It should contain almost no logic — if you find yourself writing business logic here, it belongs in `agent/` or `tools/` instead.

### `app/api/routes_chat.py`
Defines `POST /chat`. Takes a user's natural-language message, passes it into the LangGraph agent (`agent/graph.py`), and returns the agent's final response. This is the endpoint your demo UI (or Postman, or the demo video) actually hits.

### `app/api/routes_tools.py`
Optional debug/test routes like `POST /tools/resolve-rwa` that call individual tools **directly**, bypassing the LLM agent entirely. Extremely useful during development (you can verify a tool works before trusting the agent to call it correctly) and doubles as a way to generate the "evidence of a real API call" screenshots required in your submission.

### `app/api/routes_health.py`
Defines `GET /health`, returning something like `{"status": "ok"}`. Exists so that (a) you can verify the server is actually running during your demo recording, and (b) if you deploy it, uptime monitors or judges checking a live link have an instant sanity check.

---

## `app/cmc/` — the CoinMarketCap API client layer

This is the **only** part of the codebase that knows CMC's API exists. It has zero knowledge of LangChain, LangGraph, or agents — it is pure "talk to this HTTP API correctly." This isolation means you can test and fix API issues without touching any agent logic, and vice versa.

### `app/cmc/client.py`
The core HTTP client. Responsibilities:
- Holds a single `httpx.AsyncClient` instance (reused across requests for connection pooling)
- Attaches the `X-CMC_PRO_API_KEY` header to every request automatically
- Implements retry-with-backoff for transient failures (5xx errors, timeouts)
- Detects and handles rate-limit responses (429) gracefully rather than crashing
- Exposes clean async methods like `get_rwa_map()`, `get_rwa_quotes(ids)`, `get_crypto_quotes(symbols)`, `get_global_metrics()` — each mapping 1:1 to a CMC endpoint

Every tool in `app/tools/` calls into this file — nothing else makes raw HTTP calls to CMC.

### `app/cmc/schemas.py`
Pydantic models describing the **shape of CMC's responses** — e.g. `RWAQuote`, `CryptoQuote`, `GlobalMetrics`. Parsing raw JSON into these models immediately after the HTTP call catches malformed/unexpected API responses early (at the client layer) instead of causing confusing bugs deep inside the agent later. Also gives you auto-generated validation and IDE autocomplete everywhere else in the codebase.

### `app/cmc/exceptions.py`
Custom exception classes (`CMCApiError`, `CMCRateLimitError`, `CMCNotFoundError`) raised by `client.py` when something goes wrong. Having named exceptions (instead of generic `Exception`) means `tools/` and `agent/nodes.py` can catch specific failure types and respond intelligently — e.g., the agent can tell the user "rate limit hit, try again shortly" instead of just crashing.

---

## `app/tools/` — LangChain/LangGraph tool wrappers

Each file here is a **thin translation layer**: it takes an LLM-friendly input, calls the appropriate method on `cmc/client.py`, and returns an LLM-friendly output (usually a short string or structured dict, not raw JSON). These are the four tools your submission table describes — this folder is the literal, direct implementation of that table.

### `app/tools/resolve_rwa_asset.py`
Wraps `GET /v5/real-world-assets/map`. Takes a ticker/name string (`"GOLD"`), searches the map response, and returns the matching `rwa_id`. This is the **first tool in almost every chain** — nothing downstream works without a resolved ID, so this file's correctness matters disproportionately.

### `app/tools/get_rwa_market_quote.py`
Wraps `GET /v5/real-world-assets/quotes/latest`. Takes one or more `rwa_id`s and returns price, market cap, and 24h volume in a clean format. This is the "simple price check" tool — used when the user just wants one asset's numbers.

### `app/tools/compare_rwa_vs_crypto.py`
Wraps both `GET /v5/real-world-assets/quotes/latest` **and** `GET /v3/cryptocurrency/quotes/latest`, called concurrently via `asyncio.gather`. This is your standout tool — it's the one that makes the "interesting use of the API" judging criterion land, because it synthesizes two different CMC product lines into one comparative answer rather than just fetching a single number.

### `app/tools/get_global_market_metrics.py`
Wraps `GET /v1/global-metrics/quotes/latest`. Takes no parameters — always returns the current market-wide snapshot (total market cap, BTC/ETH dominance). Used to give the agent macro context to frame any single-asset answer.

### `app/tools/registry.py`
Imports all four `@tool`-decorated functions above and exposes them as a single list (`ALL_TOOLS = [...]`). `agent/graph.py` imports *only* from this file — it never imports individual tool files directly. This means adding a fifth tool later requires touching exactly two files: creating the new tool file, and adding one line here.

---

## `app/agent/` — LangGraph orchestration ("the brain")

This is where the actual agent decision-making lives: given a user message, decide which tool(s) to call, in what order, and how to turn results into a final answer.

### `app/agent/state.py`
Defines the `AgentState` (a `TypedDict` or Pydantic model) that flows through every node in the LangGraph graph — typically containing the running message history and any intermediate tool results. Every node reads from and writes to this shared state object; it's the "memory" of a single conversation turn as it passes through the graph.

### `app/agent/graph.py`
Builds the actual `StateGraph`: defines nodes (e.g., `"agent"`, `"tools"`), the edges between them, and the conditional logic for when to loop back for another tool call versus when to end and return a final answer. This is the classic ReAct-style loop: *LLM decides → tool executes → LLM sees result → LLM decides again → ... → final answer*. This file is compiled once at startup and reused for every request.

### `app/agent/nodes.py`
The individual functions referenced by `graph.py`'s nodes:
- `llm_call_node` — sends current state to the LLM, gets back either a tool call request or a final answer
- `tool_call_node` — executes whichever tool the LLM requested, using `tools/registry.py`
- `should_continue` — the conditional-edge function deciding "call another tool" vs. "stop and respond"

Keeping these separate from `graph.py` keeps the graph *structure* (nodes/edges) readable independently of the node *logic* (what each step actually does).

### `app/agent/prompts.py`
Holds the system prompt(s) that tell the LLM what role it's playing ("You are a market intelligence assistant with access to RWA and crypto data tools..."), when to use which tool, and how to format final answers. Keeping prompts in their own file (rather than inline strings in `nodes.py`) makes them easy to iterate on and version without touching orchestration code.

---

## `app/mcp/` — MCP server exposure

This layer exists so your tools are usable as **real MCP tools**, not just internal LangChain functions — meaning someone could plug your server into Claude Desktop or any other MCP client, not only your own FastAPI app. This is a direct, literal answer to the "AI Agents and Automation" track's callout of "MCP integrations."

### `app/mcp/server.py`
The MCP server entrypoint. Registers the same four tools (via `tools/registry.py`) as MCP-spec tools, and runs the MCP server process (typically over stdio or SSE, depending on the MCP SDK you use). This is a separate runnable process from `main.py` — one is your FastAPI web app, this is your MCP server; both consume the exact same underlying tool functions.

### `app/mcp/adapters.py`
Small conversion functions that translate between LangChain's tool schema (used by `agent/graph.py`) and the MCP tool schema (used by `mcp/server.py`). Exists so you write each tool's logic **once** in `app/tools/` and expose it in two different protocols without duplicating code.

---

## `app/utils/` — shared helpers

### `app/utils/cache.py`
A simple TTL (time-to-live) cache, used specifically for data that doesn't need to be fetched fresh every single call — the RWA asset map (changes rarely) and global metrics (fine to refresh every few minutes). Reduces API calls, which matters directly given the hackathon's Startup-tier rate limits.

### `app/utils/logging.py`
Configures structured logging (consistent format, log levels) used across `cmc/`, `tools/`, and `agent/`. Useful for debugging during development, and also gives you clean terminal output to show in your demo recording when the agent is "thinking" (calling tools, receiving responses).

---

## `scripts/` — one-off developer scripts (not part of the served app)

### `scripts/demo_query.py`
A standalone script that runs one full query through the agent end-to-end from the command line, without needing the FastAPI server running. Fastest way to test "does the whole pipeline work" during development, and useful for quickly generating the JSON evidence files required in your submission.

### `scripts/record_demo.md`
Not code — a checklist/script for *you* to follow when recording the demo video: what query to type, what to point out on screen, which tool calls to highlight, how long to make it. Having this written down before recording prevents rambling, dead air, or forgetting to show the actual API call happening (a required submission element).

---

## `tests/` — automated tests

### `tests/test_cmc_client.py`
Unit tests for `app/cmc/client.py` using mocked HTTP responses (no real network calls). Verifies your client correctly parses valid responses and correctly raises the right exceptions on errors/rate limits — critical because if this layer is buggy, every tool built on top of it is unreliable.

### `tests/test_tools.py`
Tests each of the four tool functions in isolation (mocking the underlying `cmc/client.py` calls), confirming each tool returns correctly-shaped output for the agent to consume.

### `tests/test_agent_graph.py`
An integration test that runs a full sample query through the compiled LangGraph graph and asserts it produces a sensible final answer, including at least one real tool call in the trace. This is your strongest evidence that "does it work" (30% of your score) is actually true, not just claimed.

---

## `ui/` — optional demo frontend

### `ui/index.html`
A minimal chat interface (HTML + vanilla JS, or swap for a Streamlit app if you'd rather write Python only) that sends messages to `POST /chat` and displays the agent's replies. This exists purely to make your demo video show a real conversation instead of raw JSON in a terminal — the single highest-leverage, lowest-effort thing you can do for your Presentation score.

---

## `docs/` — submission-required documentation

### `docs/architecture.md`
A diagram (even a simple ASCII or Mermaid one) plus a short written walkthrough of the request flow: `UI → FastAPI → LangGraph agent → Tools → CMC API → back up the chain`. Helps judges understand your system in seconds rather than reading through every file.

### `docs/api_feedback.md`
**A required submission element.** Notes on where the CMC API was confusing, missing fields, had unclear docs, or had rate limits that got in your way. Write this incrementally *as you build* — trying to reconstruct it from memory on submission day loses detail and looks thin. The hackathon organizers explicitly said this feedback matters more to them than the submission itself.

### `docs/evidence/*.json`
Raw request/response pairs for each of the four endpoints — required proof that you actually called the real CMC API, not mocked data. Generate these using `scripts/demo_query.py` or `app/api/routes_tools.py` as you build each tool, so you have real evidence saved rather than scrambling to regenerate it at the deadline.

---

## How a single request flows through this whole structure

```
User types a question in ui/index.html
        │
        ▼
POST /chat  (app/api/routes_chat.py)
        │
        ▼
LangGraph graph invoked  (app/agent/graph.py)
        │
        ▼
llm_call_node decides a tool is needed  (app/agent/nodes.py)
        │
        ▼
tool_call_node executes it  (via app/tools/registry.py)
        │
        ▼
Specific tool file runs, e.g. compare_rwa_vs_crypto.py
        │
        ▼
Calls app/cmc/client.py  →  real HTTP request to CoinMarketCap
        │
        ▼
Response validated against app/cmc/schemas.py
        │
        ▼
Result flows back up through nodes.py → graph.py → routes_chat.py
        │
        ▼
Final natural-language answer displayed in ui/index.html
```

Every file above has exactly one job in this chain — that's the whole design philosophy: **no file should do two things**, so when something breaks, you know exactly where to look.