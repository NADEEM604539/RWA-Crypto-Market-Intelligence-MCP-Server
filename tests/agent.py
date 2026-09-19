import asyncio
import os
import sys

from dotenv import load_dotenv
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

load_dotenv()

# Keep MCP subprocess access limited to the CMC API key only.
# Model-related keys remain in the local test process for the LLM calls themselves.
if not os.environ.get("CMC_API_KEY"):
    os.environ["CMC_API_KEY"] = os.getenv("CMC_API_KEY", "your-cmc-key-here")


def build_mcp_connection() -> dict:
    """MCP stdio connection spec that launches the CMC RWA MCP server (`app.server`)."""
    return {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "app.server"],
        "env": {
            "PYTHONPATH": os.getcwd(),
            "CMC_API_KEY": os.environ.get("CMC_API_KEY", "your-cmc-key-here"),
        },
        "cwd": os.getcwd(),
    }


async def load_tools():
    """Load all MCP tools exposed by the CMC RWA server as LangChain tools."""
    connection = build_mcp_connection()
    return await load_mcp_tools(session=None, connection=connection)


def build_model():
    model_name = os.getenv("LLM_MODEL", "gpt-4.1-mini")
    base_url = os.getenv("MODEL_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "No model API key found. Set OPENAI_API_KEY or AZURE_OPENAI_API_KEY in the environment or .env file."
        )


    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
    )


async def build_agent():
    """Load MCP tools and wire them into a LangGraph ReAct agent."""
    tools = await load_tools()
    model = build_model()
    agent = create_react_agent(model, tools)
    return agent, tools


async def main():
    print("🔌 Connecting to MCP Server...")

    agent, tools = await build_agent()
    print(f"✅ Successfully loaded {len(tools)} tools from MCP Server:")
    for tool in tools:
        print(f" - {tool.name}: {tool.description[:60]}...")

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
        except Exception as exc:  # pragma: no cover - diagnostic runner only
            print(f"❌ Test Failure on query [{query}]: {exc}\n")

        print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())