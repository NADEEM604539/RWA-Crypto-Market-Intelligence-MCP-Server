import time
from typing import Any, Dict, Optional

from app.cmc.client import cmc_client

_RESOLUTION_CACHE: Dict[str, Dict[str, Any]] = {}
_RESOLUTION_CACHE_TTL_SECONDS = 300


def _get_cached_resolution(key: str) -> Optional[Dict[str, Any]]:
    cached = _RESOLUTION_CACHE.get(key)
    if not cached:
        return None
    if time.time() - cached["_cached_at"] > _RESOLUTION_CACHE_TTL_SECONDS:
        _RESOLUTION_CACHE.pop(key, None)
        return None
    return cached["result"]


def _set_cached_resolution(key: str, value: Dict[str, Any]) -> None:
    _RESOLUTION_CACHE[key] = {"result": value, "_cached_at": time.time()}


async def _lookup_parent_rwa_by_token_symbol(token_symbol: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Resolve a token symbol like PAXG or XAUt back to its parent RWA asset (e.g. GOLD)."""
    start = 1

    while True:
        issuer_page = await cmc_client.get_rwa_issuers_list(api_key=api_key, limit=250, start=start)
        issuers = issuer_page.get("issuers", [])

        for issuer in issuers:
            issuer_id = issuer.get("issuer_id")
            if not issuer_id:
                continue

            issuer_details = await cmc_client.get_rwa_issuer(api_key=api_key, issuer_id=issuer_id, limit=250)
            for token in issuer_details.get("tokens", []):
                if str(token.get("symbol", "")).upper() != token_symbol:
                    continue

                rwa_id = token.get("rwa_id")
                if rwa_id is None:
                    continue

                parent_data = await cmc_client.get_rwa_quotes(api_key=api_key, rwa_id=str(rwa_id))
                parent_assets = parent_data.get("rwa_assets", [])
                if not parent_assets:
                    continue

                asset = parent_assets[0]
                return {
                    "rwa_id": asset.get("rwa_id") or rwa_id,
                    "name": asset.get("name"),
                    "symbol": asset.get("symbol"),
                    "slug": asset.get("slug"),
                    "asset_type": asset.get("asset_type"),
                    "rwa_rank": asset.get("rwa_rank"),
                    "has_tokens": asset.get("has_tokens"),
                    "resolved_via": "token_symbol",
                }

        if not issuer_page.get("has_more"):
            return None
        start += 250


async def resolve_rwa_asset(symbol: str, api_key: str) -> Dict[str, Any]:
    """
    Resolves an RWA asset symbol or a token symbol to the canonical parent RWA.

    Examples:
      - GOLD -> the asset itself
      - PAXG -> resolves to the parent GOLD asset
    """
    try:
        clean_symbol = symbol.strip().upper()

        cached = _get_cached_resolution(clean_symbol)
        if cached is not None:
            return cached

        try:
            data = await cmc_client.get_rwa_quotes(api_key=api_key, symbol=clean_symbol)
        except Exception:
            data = {"rwa_assets": []}

        rwa_assets = data.get("rwa_assets", [])
        if rwa_assets:
            asset = rwa_assets[0]
            result = {
                "rwa_id": asset.get("rwa_id"),
                "name": asset.get("name"),
                "symbol": asset.get("symbol"),
                "slug": asset.get("slug"),
                "asset_type": asset.get("asset_type"),
                "rwa_rank": asset.get("rwa_rank"),
                "has_tokens": asset.get("has_tokens"),
                "resolved_via": "rwa_symbol",
            }
            _set_cached_resolution(clean_symbol, result)
            return result

        resolved_parent = await _lookup_parent_rwa_by_token_symbol(clean_symbol, api_key=api_key)
        if resolved_parent:
            _set_cached_resolution(clean_symbol, resolved_parent)
            return resolved_parent

        return {"error": f"Asset with symbol '{clean_symbol}' not found."}
    except Exception as e:
        return {"error": f"Failed to resolve RWA symbol '{symbol}': {str(e)}"}