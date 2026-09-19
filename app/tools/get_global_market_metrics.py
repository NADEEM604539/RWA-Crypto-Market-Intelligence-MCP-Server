from typing import Any, Dict

from app.cmc.client import cmc_client
from app.utils.cache import shared_cache

# Global metrics don't need per-request freshness — refresh every 2 minutes
# rather than hitting the API on every single user query.
_CACHE_KEY = "global_market_metrics"
_CACHE_TTL_SECONDS = 120.0


async def get_global_market_metrics() -> Dict[str, Any]:
    """
    Fetches global market indicators including Bitcoin dominance, total market cap,
    24h volume, and overall crypto market statistics.

    Result is cached for a couple of minutes since this is a macro snapshot,
    not a per-asset quote that needs to be live on every call.
    """
    try:
        async def _fetch() -> Dict[str, Any]:
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

        return await shared_cache.get_or_set(_CACHE_KEY, _fetch, ttl_seconds=_CACHE_TTL_SECONDS)
    except Exception as e:
        return {"error": f"Failed to fetch global market metrics: {str(e)}"}
