import sys
from pathlib import Path

# Dynamically add the project root directory to Python's module search path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from typing import Annotated, Literal
import json

from fastmcp import FastMCP
from fastmcp.server.dependencies import CurrentHeaders
from pydantic import Field

from app.auth.auth import authenticate_and_rate_limit
from app.tools.compare_rwa_vs_crypto import compare_rwa_vs_crypto
from app.tools.get_global_market_metrics import get_global_market_metrics
from app.tools.get_rwa_issuers_info import get_rwa_issuers_info
from app.tools.get_rwa_market_quote import get_rwa_market_quote
from app.tools.resolve_rwa_asset import resolve_rwa_asset

# Type Annotations
RwaSymbol = Annotated[
    str,
    Field(
        description="RWA symbol or token symbol, for example GOLD, NVDA, or PAXG.",
        min_length=2,
        max_length=16,
        pattern=r"^[A-Za-z0-9_\-$@]+$",
    ),
]

CryptoSymbol = Annotated[
    str,
    Field(
        description="Crypto ticker symbol, for example BTC, ETH, SOL.",
        min_length=2,
        max_length=10,
        pattern=r"^[A-Za-z0-9_\-]+$",
    ),
]

RwaAssetType = Literal["commodity", "stock", "currency", "government_security", "etf", "real_estate"]

# Initialize FastMCP Server
mcp = FastMCP(
    name="CMC Real-World Asset Intelligence",
    instructions=(
        "Production-grade MCP server providing real-time pricing, issuer metadata, "
        "and comparative analysis for tokenized Real-World Assets (RWAs) and cryptocurrencies."
    ),
)


# ============================================================================
# MCP Tools Definition
# ============================================================================
@mcp.tool(name="resolve_rwa_asset")
async def resolve_rwa_asset_tool(
    symbol: RwaSymbol,
    headers: dict = CurrentHeaders(),
) -> str:
    """Resolve a real-world asset or token symbol to the canonical parent RWA record."""
    api_key, auth_error = await authenticate_and_rate_limit(headers)
    if auth_error:
        return auth_error

    result = await resolve_rwa_asset(symbol=symbol, api_key=api_key)
    return json.dumps(result, indent=2)


@mcp.tool(name="get_rwa_market_quote")
async def get_rwa_market_quote_tool(
    identifier: RwaSymbol,
    headers: dict = CurrentHeaders(),
) -> str:
    """Fetch aggregated price, market cap, volume, and token metadata for an RWA or tokenized RWA symbol."""
    api_key, auth_error = await authenticate_and_rate_limit(headers)
    if auth_error:
        return auth_error

    result = await get_rwa_market_quote(identifier=identifier, api_key=api_key)
    return json.dumps(result, indent=2)


@mcp.tool(name="compare_rwa_vs_crypto")
async def compare_rwa_vs_crypto_tool(
    rwa_symbol: RwaSymbol,
    crypto_symbol: CryptoSymbol,
    headers: dict = CurrentHeaders(),
) -> str:
    """Compare a tokenized RWA or parent RWA asset against a cryptocurrency by live market data."""
    api_key, auth_error = await authenticate_and_rate_limit(headers)
    if auth_error:
        return auth_error

    result = await compare_rwa_vs_crypto(
        rwa_symbol=rwa_symbol, crypto_symbol=crypto_symbol, api_key=api_key
    )
    return json.dumps(result, indent=2)


@mcp.tool(name="get_rwa_issuers_info")
async def get_rwa_issuers_info_tool(
    limit: Annotated[int, Field(ge=1, le=250)] = 50,
    headers: dict = CurrentHeaders(),
) -> str:
    """List registered token issuers and their token counts for the RWA market."""
    api_key, auth_error = await authenticate_and_rate_limit(headers)
    if auth_error:
        return auth_error

    result = await get_rwa_issuers_info(limit=limit, api_key=api_key)
    return json.dumps(result, indent=2)


@mcp.tool(name="get_global_market_metrics")
async def get_global_market_metrics_tool(
    headers: dict = CurrentHeaders(),
) -> str:
    """Retrieves macro crypto indicators including Bitcoin dominance and aggregate market cap."""
    api_key, auth_error = await authenticate_and_rate_limit(headers)
    if auth_error:
        return auth_error

    result = await get_global_market_metrics(api_key=api_key)
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    print(
        "🚀 Running CoinMarketCap RWA MCP Server via remote HTTP on LOCALHOST",
        file=sys.stderr,
    )
    print("🔑 Authenticating each incoming user request via 'X-CMC_PRO_API_KEY' header.", file=sys.stderr)

    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)