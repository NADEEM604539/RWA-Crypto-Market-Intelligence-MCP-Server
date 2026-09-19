import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.cmc.client import cmc_client
from app.cmc.exceptions import CMCBadRequestError, CMCNotFoundError

logger = logging.getLogger(__name__)

_RESOLUTION_CACHE: Dict[str, Dict[str, Any]] = {}
_RESOLUTION_CACHE_TTL_SECONDS = 300

# Errors that mean "CMC does not know this string as a PARENT RWA symbol". Those
# (and only those) should fall through to the token-symbol registry. Anything
# else -- bad API key, rate limit, upstream 5xx -- is a real failure and must be
# reported as such instead of being disguised as "symbol not found".
# ValueError also covers pydantic.ValidationError.
_NOT_A_PARENT_SYMBOL_ERRORS = (CMCBadRequestError, CMCNotFoundError, ValueError)

_NOT_FOUND_HINT = (
    "Pass a parent RWA symbol (e.g. GOLD) or a tokenized-asset symbol "
    "(e.g. PAXG, XAUT). Use get_rwa_issuers_info to see which issuers are tracked."
)

# Safety cap so a misbehaving `has_more` flag can never cause an unbounded loop.
_MAX_ISSUER_LIST_PAGES = 10
_MAX_TOKEN_PAGES_PER_ISSUER = 10
_PAGE_SIZE = 250


# ----------------------------------------------------------------------------
# Token registry: token symbol (PAXG) -> parent RWA id (GOLD = 1)
#
# CMC has no "look up a token by symbol" endpoint, so secondary symbols are
# found by walking issuers -> each issuer's token list
# (GET /v5/real-world-assets/issuers, `tokens[*].rwa_id`).
#
# Design notes:
#   * Incremental + early exit. Issuers are scanned smallest-first, and the scan
#     stops the moment the requested symbol is found. PAXG (Paxos, 1 token) is
#     found after a handful of calls instead of after paging through Backed
#     Assets (1000+ tokens) and Ondo (500+ tokens). Everything discovered along
#     the way is kept, so later lookups are free.
#   * Issuers with num_tokens == 0 are skipped (nothing to find).
#   * A completed scan that did not find a symbol is remembered until the TTL
#     expires, so repeated lookups of an unknown symbol cost zero API calls.
#     (Previously an empty index was treated as "not built" and rebuilt -- a
#     full issuer walk -- on every single call.)
#   * One lock serialises scans so concurrent callers share the work.
# ----------------------------------------------------------------------------
_REGISTRY_TTL_SECONDS = 300


class _TokenRegistry:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.index: Dict[str, Dict[str, Any]] = {}
        # None = issuer list not loaded yet; [] = every issuer has been scanned.
        self.pending: Optional[List[Dict[str, Any]]] = None
        self.built_at: float = 0.0

    def expired(self) -> bool:
        return bool(self.built_at) and (time.time() - self.built_at) > _REGISTRY_TTL_SECONDS


_REGISTRY = _TokenRegistry()
_REGISTRY_LOCK = asyncio.Lock()


def reset_resolver_state() -> None:
    """Clear all resolver caches (used by tests)."""
    _RESOLUTION_CACHE.clear()
    _REGISTRY.reset()


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


def _extract_assets(payload: Any) -> List[Dict[str, Any]]:
    """Accept either {"rwa_assets": [...]} or a bare list and return a list of dicts."""
    if isinstance(payload, dict):
        assets = payload.get("rwa_assets", [])
        return [a for a in assets if isinstance(a, dict)] if isinstance(assets, list) else []
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    return []


async def _load_issuers(api_key: str) -> List[Dict[str, Any]]:
    """Fetch every tracked issuer, drop empty ones, sort smallest-first."""
    issuers: List[Dict[str, Any]] = []
    start = 1
    for _ in range(_MAX_ISSUER_LIST_PAGES):
        page = await cmc_client.get_rwa_issuers_list(api_key=api_key, limit=_PAGE_SIZE, start=start)
        batch = page.get("issuers", []) if isinstance(page, dict) else []
        issuers.extend(i for i in batch if isinstance(i, dict) and i.get("issuer_id"))
        if not batch or not page.get("has_more"):
            break
        start += _PAGE_SIZE

    # num_tokens unknown (None) is kept and treated as "large" so it scans last.
    issuers = [i for i in issuers if i.get("num_tokens") != 0]
    issuers.sort(key=lambda i: i.get("num_tokens") if i.get("num_tokens") is not None else 10**9)
    return issuers


async def _scan_issuer(issuer: Dict[str, Any], api_key: str) -> None:
    """Add every token of one issuer (all pages) to the registry index."""
    start = 1
    for _ in range(_MAX_TOKEN_PAGES_PER_ISSUER):
        detail = await cmc_client.get_rwa_issuer(
            api_key=api_key, issuer_id=issuer["issuer_id"], limit=_PAGE_SIZE, start=start
        )
        tokens = detail.get("tokens", []) if isinstance(detail, dict) else []
        for token in tokens:
            symbol = str(token.get("symbol") or "").upper()
            rwa_id = token.get("rwa_id")
            if not symbol or rwa_id is None:
                continue
            # First issuer wins if two issuers share a ticker.
            _REGISTRY.index.setdefault(
                symbol,
                {
                    "rwa_id": rwa_id,
                    "token_name": token.get("name"),
                    "crypto_id": token.get("crypto_id"),
                    "issuer_id": issuer.get("issuer_id"),
                    "issuer_name": issuer.get("name"),
                },
            )
        if not tokens or not detail.get("has_more"):
            break
        start += _PAGE_SIZE


async def _find_token(token_symbol: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Return registry info for a token symbol, scanning issuers only as far as needed."""
    async with _REGISTRY_LOCK:
        if _REGISTRY.expired():
            _REGISTRY.reset()

        if token_symbol in _REGISTRY.index:
            return _REGISTRY.index[token_symbol]

        if _REGISTRY.pending is None:
            _REGISTRY.pending = await _load_issuers(api_key)
            _REGISTRY.built_at = time.time()

        while _REGISTRY.pending:
            issuer = _REGISTRY.pending[0]
            try:
                await _scan_issuer(issuer, api_key)
            except (CMCBadRequestError, CMCNotFoundError) as exc:
                # One unreadable issuer must not block resolution for everyone else.
                logger.warning("Skipping issuer %s during token scan: %s", issuer.get("issuer_id"), exc)
            # Only dropped after success/skip. A transient failure (429, 5xx)
            # propagates and this issuer is retried on the next call.
            _REGISTRY.pending.pop(0)

            if token_symbol in _REGISTRY.index:
                return _REGISTRY.index[token_symbol]

        return None


async def _lookup_parent_rwa_by_token_symbol(token_symbol: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Resolve a token symbol like PAXG or XAUt back to its parent RWA asset (e.g. GOLD)."""
    entry = await _find_token(token_symbol, api_key)
    if entry is None:
        return None

    rwa_id = entry["rwa_id"]
    parent_data = await cmc_client.get_rwa_quotes(api_key=api_key, rwa_id=str(rwa_id))
    parent_assets = _extract_assets(parent_data)
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
        "matched_token": {
            "symbol": token_symbol,
            "name": entry.get("token_name"),
            "crypto_id": entry.get("crypto_id"),
            "issuer_id": entry.get("issuer_id"),
            "issuer_name": entry.get("issuer_name"),
        },
    }


async def resolve_rwa_asset(symbol: str, api_key: str) -> Dict[str, Any]:
    """
    Resolves an RWA asset symbol or a token symbol to the canonical parent RWA.

    Examples:
      - GOLD -> the asset itself
      - PAXG -> resolves to the parent GOLD asset (and reports the issuer, Paxos)
    """
    try:
        clean_symbol = symbol.strip().upper()

        cached = _get_cached_resolution(clean_symbol)
        if cached is not None:
            return cached

        # Tier 1: is it a parent RWA symbol (GOLD, NVDA, ...)?
        try:
            data = await cmc_client.get_rwa_quotes(api_key=api_key, symbol=clean_symbol)
            rwa_assets = _extract_assets(data)
        except _NOT_A_PARENT_SYMBOL_ERRORS:
            rwa_assets = []

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

        # Tier 2: is it a token symbol (PAXG, XAUt, ...)? Look it up in the issuer registry.
        resolved_parent = await _lookup_parent_rwa_by_token_symbol(clean_symbol, api_key=api_key)
        if resolved_parent:
            _set_cached_resolution(clean_symbol, resolved_parent)
            return resolved_parent

        return {
            "error": f"Asset with symbol '{clean_symbol}' not found.",
            "hint": _NOT_FOUND_HINT,
        }
    except Exception as e:
        return {
            "error": f"Failed to resolve RWA symbol '{symbol}': {str(e)}",
            "hint": "This looks like an upstream/API problem (key, rate limit or network), not an unknown symbol. Retry shortly.",
        }
