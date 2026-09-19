# Streamlit Demo UI

A simple chat frontend for the CMC RWA agent, for testing/demoing without
needing Claude Desktop or an MCP inspector.

**Backend:** `tests/agent.py` (LangGraph ReAct agent) → `app.server` (MCP
server, spawned as a stdio subprocess) → live CoinMarketCap API.
**Frontend:** `tests/streamlit_app.py` — a thin chat UI on top of that agent.

## Setup

From the **Hackathon root** directory (the parent of `app/` and `tests/`):

```bash
python -m venv .venv
.venv\Scripts\activate                     # Windows
pip install -r app/requirements.txt
pip install -r tests/requirements.txt

# .env goes in the project root (or in app/, since app/config.py loads
# ROOT_DIR/.env — either works since ROOT_DIR is the app/ parent's app dir;
# simplest is to copy it to the Hackathon root too)
copy app\.env.example .env
```

Edit `.env` and set:
- `CMC_API_KEY` — your CoinMarketCap key (Startup tier from the hackathon signup)
- `OPENAI_API_KEY` — your OpenAI/Azure OpenAI key (the agent uses `gpt-4.1-mini`)

## Run

```bash
streamlit run tests/streamlit_app.py
```

This must be run from the Hackathon root so that:
- `python -m app.server` (the subprocess the agent spawns) can resolve the
  `app` package, and
- `tests/agent.py` is importable by the Streamlit script.

## What you'll see

- A chat interface. Type a question or click one of the example prompts in
  the sidebar (e.g. "Compare tokenized gold to Bitcoin").
- The agent decides which MCP tool(s) to call, invokes them against the live
  CMC API, and replies in natural language.
- Expand **"🔍 Tool calls & raw API responses"** under any answer to see
  exactly which tool was called, with what arguments, and the raw JSON it
  got back — this is your live "evidence of a real API call" for the demo
  recording.
- The sidebar lists all 5 loaded MCP tools with their descriptions, pulled
  live from the running MCP server.

## Troubleshooting

- **"Missing required environment variable(s)"** — `.env` isn't being found
  or doesn't have the key set. Confirm it's in the Hackathon root (or
  `app/`) and restart Streamlit (env vars are only read on process start).
- **Agent fails on first message / tools list is empty** — the MCP
  subprocess failed to start. Run `python -m app.server` directly from the
  Hackathon root first to see the raw error on stderr.
- **Slow first response** — the MCP tools are loaded once and cached via
  `st.cache_resource`; only the very first query per Streamlit process pays
  the subprocess-startup cost.
