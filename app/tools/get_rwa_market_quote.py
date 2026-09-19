from typing import Any, Dict

from app.cmc.client import cmc_client
from app.tools.resolve_rwa_asset import resolve_rwa_asset

# Known institutional / alternatively-indexed RWA tickers that CoinMarketCap
# does not resolve via a plain symbol lookup. Maps the ticker a user would
# naturally type to the ticker/key CMC actually indexes it under.
RWA_SYMBOL_ALIASES: Dict[str, str] = {
    "BUIDL": "BUIDL",   # BlackRock USD Institutional Digital Liquidity Fund
    "USDY": "USDY",     # Ondo USD Yield
    "OUSG": "OUSG",      # Ondo Short-Term US Government Bond Fund
}

# Symbols we can confidently support / suggest when resolution fails.
SUPPORTED_RWA_SYMBOLS = sorted(set(RWA_SYMBOL_ALIASES.values()) | {"GOLD", "PAXG", "XAUT"})


async def get_rwa_market_quote(identifier: str, api_key: str) -> Dict[str, Any]:
    """
    Fetches the latest aggregate market metrics for an RWA asset or token symbol.

    Token symbols like PAXG resolve to their parent RWA asset before the quote is fetched.
    Known institutional tickers (e.g. BUIDL, USDY, OUSG) are resolved via
    RWA_SYMBOL_ALIASES before being sent upstream.
    """
    try:
        clean_id = identifier.strip().upper()
        search_target = RWA_SYMBOL_ALIASES.get(clean_id, clean_id)

        resolved = None

        if search_target.isdigit():
            data = await cmc_client.get_rwa_quotes(api_key=api_key, rwa_id=search_target)
        else:
            resolved = await resolve_rwa_asset(search_target, api_key=api_key)
            if resolved.get("error") or resolved.get("rwa_id") is None:
                return {
                    "resolved": False,
                    "error": resolved.get("error", f"No market quote found for identifier '{identifier}'."),
                    "requested_identifier": identifier,
                    "normalized_identifier": clean_id,
                    "supported_identifiers": SUPPORTED_RWA_SYMBOLS,
                }
            rwa_id = resolved.get("rwa_id")
            data = await cmc_client.get_rwa_quotes(api_key=api_key, rwa_id=str(rwa_id))

        rwa_assets = data.get("rwa_assets", [])
        if not rwa_assets:
            return {
                "resolved": False,
                "error": f"No market quote found for identifier '{identifier}'.",
                "requested_identifier": identifier,
                "normalized_identifier": clean_id,
                "supported_identifiers": SUPPORTED_RWA_SYMBOLS,
            }

        asset = rwa_assets[0]
        quotes = (asset.get("quotes") or [{}])[0]

        return {
            "resolved": True,
            "rwa_id": asset.get("rwa_id"),
            "name": asset.get("name"),
            "symbol": asset.get("symbol"),
            "asset_type": asset.get("asset_type"),
            "average_tokenized_price_usd": quotes.get("average_tokenized_price"),
            "tokenized_market_cap_usd": quotes.get("tokenized_market_cap"),
            "tokenized_volume_24h_usd": quotes.get("tokenized_volume_24h"),
            "tokens_count": len(asset.get("tokens", [])),
            "tokens": [
                {
                    "symbol": t.get("symbol"),
                    "name": t.get("name"),
                    "price_usd": t.get("price"),
                    "issuer_name": t.get("issuer_name"),
                    "market_cap_usd": t.get("market_cap"),
                    "volume_24h_usd": t.get("volume_24h"),
                }
                for t in asset.get("tokens", [])
            ],
            "tradfi_markets": asset.get("tradfi_markets", []),
            "last_updated": quotes.get("last_updated"),
            "resolved_via": resolved.get("resolved_via") if resolved else "rwa_id",
        }
    except Exception as e:
        return {
            "resolved": False,
            "error": f"Failed to fetch market quote for '{identifier}': {str(e)}",
            "requested_identifier": identifier,
            "supported_identifiers": SUPPORTED_RWA_SYMBOLS,
        }
