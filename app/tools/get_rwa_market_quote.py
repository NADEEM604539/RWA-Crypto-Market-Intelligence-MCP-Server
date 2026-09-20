from typing import Any, Dict, List, Optional

from app.cmc.client import cmc_client
from app.tools.resolve_rwa_asset import resolve_rwa_asset
from app.utils.cache import shared_cache

# Troy ounce <-> gram conversion.
_GRAMS_PER_TROY_OUNCE = 31.1034768

# 1 troy oz of gold has historically traded far above $500/unit while 1 gram
# trades in the low hundreds, so this threshold cleanly separates the two
# quoting conventions for gold-backed tokens specifically. This heuristic is
# ONLY applied when the parent asset is actually gold -- applying a raw price
# threshold across all RWA types (real estate, equities, etc.) would silently
# mislabel unrelated assets, so it is intentionally scoped rather than global.
_GOLD_PER_GRAM_USD_THRESHOLD = 500.0


def _is_gold_asset(parent_symbol: Optional[str], parent_name: Optional[str]) -> bool:
    haystack = f"{parent_symbol or ''} {parent_name or ''}".upper()
    return "GOLD" in haystack or "XAU" in haystack


def _volume_to_market_cap(volume: Any, market_cap: Any) -> Optional[float]:
    """V/MC liquidity (turnover) ratio as a fraction, e.g. 0.0332 == 3.32%.
    None when market cap is missing or zero, so a ratio is never fabricated."""
    try:
        mcap = float(market_cap) if market_cap is not None else 0.0
        vol = float(volume) if volume is not None else 0.0
    except (TypeError, ValueError):
        return None
    return round(vol / mcap, 6) if mcap > 0 else None


def _annotate_token_unit(token: Dict[str, Any], is_gold: bool) -> Dict[str, Any]:
    """Tag a gold token with its likely price unit (gram vs troy ounce) and
    add a normalized per-troy-ounce price so callers can compare tokens on
    equal footing. Non-gold assets are left untouched (unit: None) since we
    have no reliable signal for their quoting convention."""
    if not is_gold:
        token["unit"] = None
        token["normalized_price_per_oz_usd"] = None
        return token

    price = token.get("price_usd")
    if price is None:
        token["unit"] = "unknown"
        token["normalized_price_per_oz_usd"] = None
        return token

    is_per_gram = price < _GOLD_PER_GRAM_USD_THRESHOLD
    token["unit"] = "gram" if is_per_gram else "troy_ounce"
    token["normalized_price_per_oz_usd"] = round(
        price * _GRAMS_PER_TROY_OUNCE if is_per_gram else price, 2
    )
    return token

# Known institutional / alternatively-indexed RWA tickers that CoinMarketCap
# does not resolve via a plain symbol lookup. Maps the ticker a user would
# naturally type to the ticker/key CMC actually indexes it under.
#
# NOTE: As verified against the live RWA issuer registry, neither BUIDL,
# OUSG, nor USDY currently resolve as standalone RWA symbols or via the
# token-symbol fallback search in this dataset -- there is no BlackRock
# issuer entry at all, and Ondo Assets' 551 tokens are not addressable by
# these tickers through the exposed lookup path. Rather than proxy to
# another symbol that also fails (which previously produced a confusing
# double failure), these are left unmapped so the fallback error below is
# accurate. Populate this dict with a *verified working* alias as soon as
# one is confirmed (e.g. by inspecting Ondo Assets' token list directly via
# the issuer-detail lookup, which is not currently exposed as an MCP tool).
RWA_SYMBOL_ALIASES: Dict[str, str] = {}

# Institutional tickers known to be requested but NOT currently indexed by
# this data source, surfaced separately so the error message is honest
# instead of implying they're supported.
KNOWN_UNTRACKED_IDENTIFIERS = ["BUIDL", "OUSG", "USDY"]

# Only used if the live lookup below fails outright (upstream outage, bad
# key, etc.) -- kept deliberately tiny so it can never quietly drift out of
# sync with the real token set the way a full hand-maintained list did (the
# previous static SUPPORTED_RWA_SYMBOLS list was missing XAUT0 and XAU
# despite both being live gold tokens, since nobody updates a hardcoded
# list when CMC adds a new one).
_FALLBACK_SUPPORTED_RWA_SYMBOLS = ["GOLD", "PAXG", "XAUT"]

_SUPPORTED_SYMBOLS_CACHE_KEY = "rwa_market_quote:supported_symbols:gold"
_SUPPORTED_SYMBOLS_CACHE_TTL_SECONDS = 60.0


async def _get_supported_rwa_symbols(api_key: str) -> List[str]:
    """
    Returns the live set of resolvable RWA/token symbols by reading the
    GOLD parent asset's own token list -- the same live data this tool
    already serves to callers -- instead of a hand-maintained list that
    silently goes stale every time CMC adds a new gold token.

    Reuses resolve_rwa_asset() rather than hardcoding GOLD's rwa_id, so this
    doesn't reintroduce the exact "hardcoded value nobody updates" problem
    it's meant to fix. Cached for 60s via the shared TTL cache so a burst of
    "not found" lookups doesn't turn into a burst of extra upstream calls.
    Any failure degrades to the small static fallback rather than raising --
    building an error hint must never itself become the error the caller sees.
    """
    async def _fetch() -> List[str]:
        try:
            resolved = await resolve_rwa_asset("GOLD", api_key=api_key)
            rwa_id = resolved.get("rwa_id")
            if rwa_id is None:
                return list(_FALLBACK_SUPPORTED_RWA_SYMBOLS)

            data = await cmc_client.get_rwa_quotes(api_key=api_key, rwa_id=str(rwa_id))
            rwa_assets = data.get("rwa_assets", []) if isinstance(data, dict) else []
            if not rwa_assets:
                return list(_FALLBACK_SUPPORTED_RWA_SYMBOLS)

            symbols = {"GOLD"}
            for token in rwa_assets[0].get("tokens", []):
                symbol = token.get("symbol")
                if symbol:
                    symbols.add(str(symbol).upper())
            return sorted(symbols)
        except Exception:
            return list(_FALLBACK_SUPPORTED_RWA_SYMBOLS)

    return await shared_cache.get_or_set(
        _SUPPORTED_SYMBOLS_CACHE_KEY, _fetch, ttl_seconds=_SUPPORTED_SYMBOLS_CACHE_TTL_SECONDS
    )


async def get_rwa_market_quote(identifier: str, api_key: str) -> Dict[str, Any]:
    """
    Fetches the latest aggregate market metrics for an RWA asset or token symbol.

    Token symbols like PAXG resolve to their parent RWA asset before the quote is fetched.
    Known institutional tickers (e.g. BUIDL, USDY, OUSG) are resolved via
    RWA_SYMBOL_ALIASES before being sent upstream.
    """
    try:
        clean_id = identifier.strip().upper()

        # Fast-path rejection for identifiers that are syntactically valid
        # (pass the MCP schema, max 64 chars) but are far longer than any
        # real RWA/token symbol (all known symbols are <= 16 chars). This
        # avoids burning a full issuer-list scan + API round trip in
        # resolve_rwa_asset() on input that can never resolve, and returns
        # the same graceful JSON shape as every other "not found" case.
        if len(clean_id) > 16:
            return {
                "resolved": False,
                "error": f"Identifier '{clean_id}' exceeds the maximum supported symbol length of 16 characters.",
                "requested_identifier": identifier,
                "normalized_identifier": clean_id,
                "supported_identifiers": await _get_supported_rwa_symbols(api_key),
            }

        search_target = RWA_SYMBOL_ALIASES.get(clean_id, clean_id)

        resolved = None

        if search_target.isdigit():
            data = await cmc_client.get_rwa_quotes(api_key=api_key, rwa_id=search_target)
        else:
            resolved = await resolve_rwa_asset(search_target, api_key=api_key)
            if resolved.get("error") or resolved.get("rwa_id") is None:
                hint = resolved.get("hint")
                if clean_id in KNOWN_UNTRACKED_IDENTIFIERS:
                    hint = (
                        f"'{clean_id}' is a known institutional/treasury ticker that is not "
                        "currently indexed by this data source (no matching issuer or token "
                        "record found). This is not a lookup bug -- the data simply isn't tracked yet."
                    )
                return {
                    "resolved": False,
                    "error": resolved.get("error", f"No market quote found for identifier '{identifier}'."),
                    "hint": hint,
                    "requested_identifier": identifier,
                    "normalized_identifier": clean_id,
                    "supported_identifiers": await _get_supported_rwa_symbols(api_key),
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
                "supported_identifiers": await _get_supported_rwa_symbols(api_key),
            }

        asset = rwa_assets[0]
        quotes = (asset.get("quotes") or [{}])[0]
        is_gold = _is_gold_asset(asset.get("symbol"), asset.get("name"))

        token_rows = [
            _annotate_token_unit(
                {
                    "symbol": t.get("symbol"),
                    "name": t.get("name"),
                    "price_usd": t.get("price"),
                    "issuer_name": t.get("issuer_name"),
                    "market_cap_usd": t.get("market_cap"),
                    "volume_24h_usd": t.get("volume_24h"),
                    "volume_to_market_cap_ratio": _volume_to_market_cap(
                        t.get("volume_24h"), t.get("market_cap")
                    ),
                },
                is_gold=is_gold,
            )
            for t in asset.get("tokens", [])
        ]

        # When the caller asked for a specific token (e.g. PAXG), surface that
        # token's own record so it isn't buried inside the parent aggregate.
        requested_symbols = {clean_id, search_target}
        requested_token = next(
            (row for row in token_rows if str(row.get("symbol") or "").upper() in requested_symbols),
            None,
        )

        proxy_note = None
        if clean_id != search_target:
            proxy_note = (
                f"'{clean_id}' has no standalone primary listing in CMC's RWA data; "
                f"showing proxied data for '{search_target}' instead."
            )
            # NOTE: with RWA_SYMBOL_ALIASES currently empty, this branch is
            # unreachable until a verified alias is added above.

        return {
            "resolved": True,
            "proxy_note": proxy_note,
            "rwa_id": asset.get("rwa_id"),
            "name": asset.get("name"),
            "symbol": asset.get("symbol"),
            "asset_type": asset.get("asset_type"),
            "average_tokenized_price_usd": quotes.get("average_tokenized_price"),
            "tokenized_market_cap_usd": quotes.get("tokenized_market_cap"),
            "tokenized_volume_24h_usd": quotes.get("tokenized_volume_24h"),
            "volume_to_market_cap_ratio": _volume_to_market_cap(
                quotes.get("tokenized_volume_24h"), quotes.get("tokenized_market_cap")
            ),
            "tokens_count": len(token_rows),
            "requested_token": requested_token,
            "tokens": token_rows,
            "tradfi_markets": asset.get("tradfi_markets", []),
            "last_updated": quotes.get("last_updated"),
            "resolved_via": resolved.get("resolved_via") if resolved else "rwa_id",
        }
    except Exception as e:
        return {
            "resolved": False,
            "error": f"Failed to fetch market quote for '{identifier}': {str(e)}",
            "requested_identifier": identifier,
            "supported_identifiers": _FALLBACK_SUPPORTED_RWA_SYMBOLS,
        }
