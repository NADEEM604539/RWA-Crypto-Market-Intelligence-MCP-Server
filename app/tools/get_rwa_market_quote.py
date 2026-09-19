from typing import Any, Dict

from app.cmc.client import cmc_client
from app.tools.resolve_rwa_asset import resolve_rwa_asset


async def get_rwa_market_quote(identifier: str, api_key: str) -> Dict[str, Any]:
    """
    Fetches the latest aggregate market metrics for an RWA asset or token symbol.

    Token symbols like PAXG resolve to their parent RWA asset before the quote is fetched.
    """
    try:
        clean_id = identifier.strip()
        resolved = None

        if clean_id.isdigit():
            data = await cmc_client.get_rwa_quotes(api_key=api_key, rwa_id=clean_id)
        else:
            resolved = await resolve_rwa_asset(clean_id, api_key=api_key)
            if resolved.get("error"):
                return {"error": resolved["error"]}
            rwa_id = resolved.get("rwa_id")
            if rwa_id is None:
                return {"error": f"No market quote found for identifier '{identifier}'."}
            data = await cmc_client.get_rwa_quotes(api_key=api_key, rwa_id=str(rwa_id))

        rwa_assets = data.get("rwa_assets", [])
        if not rwa_assets:
            return {"error": f"No market quote found for identifier '{identifier}'."}

        asset = rwa_assets[0]
        quotes = (asset.get("quotes") or [{}])[0]

        return {
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
        return {"error": f"Failed to fetch market quote for '{identifier}': {str(e)}"}