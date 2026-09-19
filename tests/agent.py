import asyncio
import os

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

load_dotenv()

# Model and external credentials resolution
CMC_KEY = os.getenv("CMC_API_KEY")


def get_mcp_server_config() -> dict:
    """Return the MCP server connection config.

    Defaults to the local streamable-HTTP server started with
    `python -m app.server` (http://127.0.0.1:8000/mcp), matching how the
    server actually runs in this project.

    Override via env vars if you're pointing at a different deployment:
      MCP_SERVER_URL   e.g. https://cmcserver.fastmcp.app/mcp
      MCP_TRANSPORT    "http" (default) or "stdio" (spawns `npx mcp-remote`)
      NODE_NPX_PATH    path to npx, only used when MCP_TRANSPORT=stdio
    """
    if not CMC_KEY:
        raise RuntimeError(
            "CMC_API_KEY is not set. Add it to your .env file (see app/.env.example)."
        )

    server_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
    transport = os.getenv("MCP_TRANSPORT", "http").strip().lower()

    if transport == "stdio":
        npx_path = os.getenv("NODE_NPX_PATH", "npx")
        return {
            "cmc_rwa": {
                "command": npx_path,
                "args": [
                    "mcp-remote",
                    server_url,
                    "--header",
                    "X-CMC_PRO_API_KEY:${CMC_API_KEY}",
                ],
                "env": {"CMC_API_KEY": CMC_KEY},
            }
        }

    return {
        "cmc_rwa": {
            "transport": "http",  # FastMCP HTTP streamable transport
            "url": server_url,
            "headers": {"X-CMC_PRO_API_KEY": CMC_KEY},
        }
    }


def build_model():
    """Instantiate the ChatOpenAI or Azure model client."""
    model_name = os.getenv("LLM_MODEL", "gpt-4o-mini")
    base_url = os.getenv("MODEL_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "No valid API key found. Set OPENAI_API_KEY or AZURE_OPENAI_API_KEY in .env"
        )

    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
    )


# ----------------------------------------------------------------------------
# build_agent()
#
# Shared entrypoint used both by this script's own CLI test run (main(),
# below) and by tests/streamlit_app.py, so the two never duplicate the
# "connect to MCP server, load tools, build a ReAct agent" logic.
# ----------------------------------------------------------------------------
async def build_agent():
    """Connects to the MCP server, loads its tools, and builds a LangGraph
    ReAct agent. Returns (agent, tools)."""
    server_config = get_mcp_server_config()
    model = build_model()

    client = MultiServerMCPClient(server_config)
    tools = await client.get_tools()
    agent = create_react_agent(model, tools)
    return agent, tools


async def main():
    print("🔌 Connecting to MCP Server...")

    agent, tools = await build_agent()

    print(f"✅ Successfully loaded {len(tools)} tool(s) from MCP Server:")
    for tool in tools:
        desc = getattr(tool, "description", "No description available")
        print(f" - {tool.name}: {desc[:60]}...")

    queries = [
        "Find the canonical internal metadata and rwa_id for symbol 'GOLD'.",
        "Get the aggregate market quote, average price, and tokenized market cap for 'GOLD'.",
        "Compare the tokenized market performance of PAXG against BTC.",
        "List the top 5 registered Real-World Asset issuers along with their active token counts.",
        "Retrieve global crypto market indicators including Bitcoin dominance and aggregate market cap.",
    ]

    print("\n🤖 Running Agent Suite Across All MCP Tools...\n" + "=" * 60)

    for idx, query in enumerate(queries, 1):
        print(f"\n[Test {idx}/{len(queries)}] ❓ Query: {query}\n")

        try:
            response = await agent.ainvoke({"messages": [("user", query)]})
            final_message = response["messages"][-1].content
            print(f"💬 Agent Response:\n{final_message}\n")
        except Exception as exc:
            print(f"❌ Test Failure on query [{query}]: {exc}\n")

        print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())
