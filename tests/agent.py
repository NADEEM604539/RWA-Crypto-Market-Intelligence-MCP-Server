import asyncio
import os
import sys

from dotenv import load_dotenv
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

load_dotenv()

# Ensure environment variables are accessible
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "your-openai-key-here")
os.environ["CMC_API_KEY"] = os.getenv("CMC_API_KEY", "your-cmc-key-here")


async def main():
    connection = {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "app.server"],
        "env": {
            "PYTHONPATH": os.getcwd(),
            "CMC_API_KEY": os.environ.get("CMC_API_KEY", ""),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
        },
        "cwd": os.getcwd(),
    }

    print("🔌 Connecting to MCP Server...")

    # Load MCP tools into LangChain format
    tools = await load_mcp_tools(session=None, connection=connection)
    print(f"✅ Successfully loaded {len(tools)} tools from MCP Server:")
    for tool in tools:
        print(f" - {tool.name}: {tool.description[:60]}...")

    # Initialize LangChain Agent
    model = ChatOpenAI(
        model="gpt-4.1-mini",
        base_url="https://openai-rg-nadeem.openai.azure.com/openai/v1",
        temperature=0,
    )
    agent = create_react_agent(model, tools)

    # Full Test Suite testing all 5 registered tools
    queries = [
        # Tool 1: resolve_rwa_asset
        "Find the canonical internal metadata and rwa_id for symbol 'GOLD'.",
        
        # Tool 2: get_rwa_market_quote
        "Get the aggregate market quote, average price, and tokenized market cap for 'GOLD'.",
        
        # Tool 3: compare_rwa_vs_crypto (verifies PAXG isolated token fallback vs BTC)
        "Compare the tokenized market performance of PAXG against BTC.",
        
        # Tool 4: get_rwa_issuers_info
        "List the top 5 registered Real-World Asset issuers along with their active token counts.",
        
        # Tool 5: get_global_market_metrics
        "Retrieve global crypto market indicators including Bitcoin dominance and aggregate market cap.",
    ]

    print("\n🤖 Running Agent Suite Across All MCP Tools...\n" + "=" * 60)

    for idx, query in enumerate(queries, 1):
        print(f"\n[Test {idx}/{len(queries)}] ❓ Query: {query}\n")
        
        try:
            response = await agent.ainvoke({"messages": [("user", query)]})
            final_message = response["messages"][-1].content
            print(f"💬 Agent Response:\n{final_message}\n")
        except Exception as e:
            print(f"❌ Test Failure on query [{query}]: {e}\n")
            
        print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())