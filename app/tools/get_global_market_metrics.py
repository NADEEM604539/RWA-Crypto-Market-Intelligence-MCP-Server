from typing import Any, Dict
from app.cmc.client import cmc_client


async def get_global_market_metrics() -> Dict[str, Any]:
    """
    Fetches global market indicators including Bitcoin dominance, total market cap, 
    24h volume, and overall crypto market statistics.
    """
    try:
        data = await cmc_client.get_global_metrics()
        quotes = data.get("quote", {}).get("USD", {})

        return {
            "btc_dominance": data.get("btc_dominance"),
            "eth_dominance": data.get("eth_dominance"),
            "active_cryptocurrencies": data.get("active_cryptocurrencies"),
            "total_market_cap_usd": quotes.get("total_market_cap"),
            "total_volume_24h_usd": quotes.get("total_volume_24h"),
            "last_updated": quotes.get("last_updated"),
        }
    except Exception as e:
        return {"error": f"Failed to fetch global market metrics: {str(e)}"}