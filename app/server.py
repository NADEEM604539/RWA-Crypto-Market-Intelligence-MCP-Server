from typing import Annotated, Literal

import json
import sys

from mcp.server.fastmcp import FastMCP as MCPServer
from pydantic import Field

from app.config import settings
from app.tools.resolve_rwa_asset import resolve_rwa_asset
from app.tools.get_rwa_market_quote import get_rwa_market_quote
from app.tools.compare_rwa_vs_crypto import compare_rwa_vs_crypto
from app.tools.get_rwa_issuers_info import get_rwa_issuers_info
from app.tools.get_global_market_metrics import get_global_market_metrics

RwaSymbol = Annotated[
    str,
    Field(
        description="RWA symbol or token symbol, for example GOLD, NVDA, or PAXG.",
        min_length=2,
        max_length=16,
        pattern=r"^[A-Z0-9$@\-]+$",
    ),
]

CryptoSymbol = Annotated[
    str,
    Field(
        description="Crypto ticker symbol, for example BTC, ETH, SOL.",
        min_length=2,
        max_length=10,
        pattern=r"^[A-Z0-9]+$",
    ),
]

RwaAssetType = Literal["commodity", "stock", "currency", "government_security", "etf", "real_estate"]

# Initialize FastMCP Server
mcp = MCPServer(
    name="CMC Real-World Asset Intelligence",
    instructions=(
        "Production-grade MCP server providing real-time pricing, issuer metadata, "
        "and comparative analysis for tokenized Real-World Assets (RWAs) and cryptocurrencies."
    )
)


@mcp.tool(name="resolve_rwa_asset")
async def resolve_rwa_asset_tool(symbol: RwaSymbol) -> str:
    """Resolve a real-world asset or token symbol to the canonical parent RWA record."""
    result = await resolve_rwa_asset(symbol=symbol)
    return json.dumps(result, indent=2)


@mcp.tool(name="get_rwa_market_quote")
async def get_rwa_market_quote_tool(identifier: RwaSymbol) -> str:
    """Fetch aggregated price, market cap, volume, and token metadata for an RWA or tokenized RWA symbol."""
    result = await get_rwa_market_quote(identifier=identifier)
    return json.dumps(result, indent=2)


@mcp.tool(name="compare_rwa_vs_crypto")
async def compare_rwa_vs_crypto_tool(rwa_symbol: RwaSymbol, crypto_symbol: CryptoSymbol) -> str:
    """Compare a tokenized RWA or parent RWA asset against a cryptocurrency by live market data."""
    result = await compare_rwa_vs_crypto(rwa_symbol=rwa_symbol, crypto_symbol=crypto_symbol)
    return json.dumps(result, indent=2)


@mcp.tool(name="get_rwa_issuers_info")
async def get_rwa_issuers_info_tool(limit: Annotated[int, Field(ge=1, le=250)] = 50) -> str:
    """List registered token issuers and their token counts for the RWA market."""
    result = await get_rwa_issuers_info(limit=limit)
    return json.dumps(result, indent=2)


@mcp.tool(name="get_global_market_metrics")
async def get_global_market_metrics_tool() -> str:
    """Retrieves macro crypto indicators including Bitcoin dominance and aggregate market cap."""
    result = await get_global_market_metrics()
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    print("🚀 Running CoinMarketCap RWA MCP Server via stdio...", file=sys.stderr)
    mcp.run(transport="stdio")