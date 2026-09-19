"""
Streamlit demo UI for the CMC RWA & Crypto Market Intelligence agent.

Backend: the LangGraph ReAct agent defined in `tests/agent.py`, which in turn
talks to the `app.server` MCP server (stdio subprocess) — which talks to the
live CoinMarketCap API. This file only adds a chat frontend on top of that
existing agent; it does not duplicate any tool/business logic.

Run from the Hackathon root directory (the parent of `app/` and `tests/`):

    streamlit run tests/streamlit_app.py

Requires CMC_API_KEY and OPENAI_API_KEY in your .env (see app/.env.example).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# Ensure `agent.py` in the same directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

load_dotenv()

from agent import build_agent  # noqa: E402
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

st.set_page_config(
    page_title="CMC RWA Agent — Demo",
    page_icon="📊",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Async bridge — Maintains a persistent event loop across Streamlit script runs.
# ---------------------------------------------------------------------------
def get_event_loop() -> asyncio.AbstractEventLoop:
    """Retrieve or create a persistent event loop for the current thread."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def run_async(coro):
    """Executes an async coroutine synchronously on the active event loop."""
    loop = get_event_loop()
    return loop.run_until_complete(coro)


@st.cache_resource(show_spinner="🔌 Connecting to MCP server and loading tools...")
def get_agent_and_tools():
    """Builds the agent once per Streamlit session process and caches it.

    Spawns the `app.server` MCP subprocess (via tests/agent.py's
    build_agent()) and loads its tools into the LangGraph ReAct agent.
    """
    return run_async(build_agent())


def extract_tool_trace(messages) -> list[str]:
    """Pulls a readable trace of tool calls + raw responses from messages."""
    trace: list[str] = []
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                trace.append(f"→ CALL {tc['name']}({tc.get('args', {})})")
        elif isinstance(m, ToolMessage):
            trace.append(f"← RESULT [{m.name}]\n{m.content}")
    return trace


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("📊 CMC Real-World Asset Intelligence — Agent Demo")
st.caption(
    "LangGraph agent → MCP server (`app.server`) → live CoinMarketCap API. "
    "Built for CMC Hackathon · AI Agents and Automation track"
)

missing_env = [k for k in ("CMC_API_KEY", "OPENAI_API_KEY") if not os.environ.get(k)]
if missing_env:
    st.error(
        f"Missing required environment variable(s): {', '.join(missing_env)}.\n\n"
        "Add them to a `.env` file in the project root (see `app/.env.example`) "
        "and restart Streamlit."
    )
    st.stop()

try:
    agent, tools = get_agent_and_tools()
except Exception as exc:
    st.error(f"Failed to start the MCP agent: {exc}")
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_query" not in st.session_state:
    st.session_state.pending_query = None

with st.sidebar:
    st.subheader("🔧 Loaded MCP Tools")
    st.caption(f"{len(tools)} tools connected via stdio")
    for t in tools:
        with st.expander(t.name):
            st.write(t.description)

    st.divider()
    st.subheader("💡 Try asking")
    examples = [
        "Compare tokenized gold to Bitcoin",
        "What's the global crypto market cap and BTC dominance right now?",
        "List the top 5 RWA issuers",
        "What's the price of PAXG?",
        "Resolve the rwa_id for GOLD",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex-{ex}", use_container_width=True):
            st.session_state.pending_query = ex
            st.rerun()

    st.divider()
    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# Render conversation history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("trace"):
            with st.expander("🔍 Tool calls & raw API responses"):
                for line in msg["trace"]:
                    st.code(line, language="text")

# Get the next query — either typed or clicked from the sidebar examples
query = st.chat_input("Ask about RWAs, tokens, or crypto markets...")
if not query and st.session_state.pending_query:
    query = st.session_state.pending_query
    st.session_state.pending_query = None

if query:
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        with st.spinner("Calling CMC API tools..."):
            try:
                response = run_async(agent.ainvoke({"messages": [("user", query)]}))
                final_message = response["messages"][-1].content
                trace = extract_tool_trace(response["messages"])

                st.markdown(final_message)
                if trace:
                    with st.expander("🔍 Tool calls & raw API responses", expanded=False):
                        for line in trace:
                            st.code(line, language="text")

                st.session_state.messages.append(
                    {"role": "assistant", "content": final_message, "trace": trace}
                )
            except Exception as exc:  # noqa: BLE001
                error_text = f"⚠️ Agent failed: {exc}"
                st.error(error_text)
                st.session_state.messages.append(
                    {"role": "assistant", "content": error_text, "trace": []}
                )