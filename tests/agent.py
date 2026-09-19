import asyncio
import os
import sys

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

load_dotenv()

# Model and external credentials resolution
CMC_KEY = os.getenv("CMC_API_KEY")


def get_mcp_server_config() -> dict:
    """Return the Streamable HTTP server configuration dictionary."""
    return {
        "cmc_rwa": {
            "transport": "http",                     # FastMCP HTTP streamable transport
            "url": "http://127.0.0.1:8000/mcp",      # Default fastmcp endpoint route
            "headers": {
                "X-CMC_PRO_API_KEY": CMC_KEY
            }
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


async def main():
    print("🔌 Connecting to FastMCP Server over Streamable HTTP...")
    
    server_config = get_mcp_server_config()
    model = build_model()

    # Manage connection life cycle using MultiServerMCPClient
    async with MultiServerMCPClient(server_config) as client:
        # Load tools from the connected HTTP session
        tools = await client.get_tools()
        
        print(f"✅ Successfully loaded {len(tools)} tool(s) from MCP Server:")
        for tool in tools:
            desc = getattr(tool, "description", "No description available")
            print(f" - {tool.name}: {desc[:60]}...")

        # Construct the LangGraph ReAct Agent
        agent = create_react_agent(model, tools)

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