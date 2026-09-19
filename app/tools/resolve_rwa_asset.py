import asyncio
import time
from typing import Any, Dict, Optional

from app.cmc.client import cmc_client

_RESOLUTION_CACHE: Dict[str, Dict[str, Any]] = {}
_RESOLUTION_CACHE_TTL_SECONDS = 300

# ----------------------------------------------------------------------------
# Shared token index
#
# Previously, every *unresolved* symbol (a token ticker like PAXG rather than
# a top-level RWA symbol like GOLD) triggered its own full walk of every
# issuer + every issuer's token list (O(issuers * tokens_per_issuer) API
# calls), even if a request a second earlier had just walked the exact same
# data looking for a different symbol.
#
# Instead, build the issuer/token -> parent-RWA index ONCE, cache it for
# _TOKEN_INDEX_TTL_SECONDS, and let every symbol lookup within that window
# do an O(1) dict lookup against it. The index is built lazily on first use
# and rebuilt (one full scan) only after it expires. Concurrent callers that
# arrive while a build is in flight await the same in-progress build instead
# of kicking off duplicate scans.
# ----------------------------------------------------------------------------
_TOKEN_INDEX: Dict[str, Dict[str, Any]] = {}
_TOKEN_INDEX_BUILT_AT: float = 0.0
_TOKEN_INDEX_TTL_SECONDS = 300
_TOKEN_INDEX_LOCK = asyncio.Lock()


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


async def _build_token_index(api_key: str) -> Dict[str, Dict[str, Any]]:
    """Walk every issuer and every issuer's tokens exactly once, returning a
    dict keyed by uppercase token symbol -> {"rwa_id": ...} for its parent RWA."""
    index: Dict[str, Dict[str, Any]] = {}
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
                token_symbol = str(token.get("symbol", "")).upper()
                rwa_id = token.get("rwa_id")
                if not token_symbol or rwa_id is None or token_symbol in index:
                    continue
                index[token_symbol] = {"rwa_id": rwa_id}

        if not issuer_page.get("has_more"):
            break
        start += 250

    return index


async def _get_token_index(api_key: str) -> Dict[str, Dict[str, Any]]:
    """Returns the shared token->rwa_id index, rebuilding it if missing/expired."""
    global _TOKEN_INDEX, _TOKEN_INDEX_BUILT_AT

    if _TOKEN_INDEX and (time.time() - _TOKEN_INDEX_BUILT_AT) < _TOKEN_INDEX_TTL_SECONDS:
        return _TOKEN_INDEX

    async with _TOKEN_INDEX_LOCK:
        # Re-check after acquiring the lock: another concurrent call may have
        # just finished the rebuild while we were waiting on it.
        if _TOKEN_INDEX and (time.time() - _TOKEN_INDEX_BUILT_AT) < _TOKEN_INDEX_TTL_SECONDS:
            return _TOKEN_INDEX

        _TOKEN_INDEX = await _build_token_index(api_key)
        _TOKEN_INDEX_BUILT_AT = time.time()
        return _TOKEN_INDEX


async def _lookup_parent_rwa_by_token_symbol(token_symbol: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Resolve a token symbol like PAXG or XAUt back to its parent RWA asset (e.g. GOLD),
    using the shared, TTL-cached token index instead of a fresh full scan per call."""
    index = await _get_token_index(api_key)
    entry = index.get(token_symbol)
    if entry is None:
        return None

    rwa_id = entry["rwa_id"]
    parent_data = await cmc_client.get_rwa_quotes(api_key=api_key, rwa_id=str(rwa_id))
    parent_assets = parent_data.get("rwa_assets", [])
    if not parent_assets:
        return None

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