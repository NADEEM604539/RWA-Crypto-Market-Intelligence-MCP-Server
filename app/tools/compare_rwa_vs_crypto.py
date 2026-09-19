import asyncio
from typing import Any, Dict, Optional

from app.cmc.client import cmc_client
from app.tools.resolve_rwa_asset import resolve_rwa_asset


# ============================================================================
# Shared payload-normalization helpers
# ============================================================================
def _normalize_rwa_payload(payload: Any) -> Dict[str, Any]:
    """Normalize one of the multiple RWA payload shapes to a single asset dict."""
    if not payload:
        return {}

    if isinstance(payload, dict):
        if "data" in payload and isinstance(payload["data"], dict):
            payload = payload["data"]
        if isinstance(payload.get("rwa_assets"), list):
            rwa_assets = payload["rwa_assets"]
            return rwa_assets[0] if rwa_assets else {}
        if any(key in payload for key in ("symbol", "name", "rwa_id", "quotes", "tokens")):
            return payload

    if isinstance(payload, list):
        return payload[0] if payload and isinstance(payload[0], dict) else {}

    return {}


def _extract_token_by_symbol(rwa_data: Dict[str, Any], target_symbol: str) -> Optional[Dict[str, Any]]:
    """Filters child tokens inside an RWA asset group if a specific token symbol was requested."""
    tokens = rwa_data.get("tokens", [])
    if isinstance(tokens, list):
        for token in tokens:
            if isinstance(token, dict) and token.get("symbol", "").upper() == target_symbol:
                return token
    return None


def _normalize_crypto_payload(payload: Any, symbol: str) -> Dict[str, Any]:
    """Defensively extracts cryptocurrency quote data regardless of response shape or ID keying."""
    def _find_symbol_match(node: Any) -> Dict[str, Any]:
        if isinstance(node, dict):
            if str(node.get("symbol", "")).upper() == symbol:
                return node
            if str(node.get("name", "")).upper() == symbol:
                return node
            if str(node.get("slug", "")).upper() == symbol:
                return node
            for key, value in node.items():
                if str(key).upper() == symbol:
                    if isinstance(value, dict):
                        return value
                    if isinstance(value, list) and value and isinstance(value[0], dict):
                        return value[0]
                found = _find_symbol_match(value)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = _find_symbol_match(item)
                if found:
                    return found
        return {}

    if not payload:
        return {}

    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]

    if isinstance(payload, list):
        for item in payload:
            found = _find_symbol_match(item)
            if found:
                return found
        return payload[0] if payload and isinstance(payload[0], dict) else {}

    if isinstance(payload, dict):
        if symbol in payload:
            candidate = payload[symbol]
            if isinstance(candidate, dict):
                return candidate
            if isinstance(candidate, list) and candidate:
                return candidate[0] if isinstance(candidate[0], dict) else {}

        found = _find_symbol_match(payload)
        if found:
            return found

    return {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce a possibly-missing/None/str numeric value to a float, defaulting safely."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_crypto_quote(api_response: Any, symbol: str) -> Dict[str, Any]:
    """
    Safely extract a cryptocurrency's USD quote from a CMC
    /v1/cryptocurrency/quotes/latest (or /v3 equivalent) response.

    Handles the case where `data[symbol]` is returned as a list (e.g. when
    multiple tokens share the same ticker) instead of a dict, and guarantees
    price_usd / market_cap_usd / volume_24h_usd always resolve to a float,
    defaulting to 0.0 when missing or None.
    """
    symbol_upper = (symbol or "").strip().upper()

    token_data = _normalize_crypto_payload(api_response, symbol_upper)

    if isinstance(token_data, list):
        token_data = token_data[0] if token_data and isinstance(token_data[0], dict) else {}
    if not isinstance(token_data, dict):
        token_data = {}

    raw_quote = token_data.get("quote", {})
    quote_usd = raw_quote.get("USD", {}) if isinstance(raw_quote, dict) else {}
    if not isinstance(quote_usd, dict):
        quote_usd = {}

    return {
        "symbol": token_data.get("symbol", symbol_upper),
        "name": token_data.get("name", symbol_upper),
        "price_usd": _safe_float(quote_usd.get("price"), 0.0),
        "market_cap_usd": _safe_float(quote_usd.get("market_cap"), 0.0),
        "volume_24h_usd": _safe_float(quote_usd.get("volume_24h"), 0.0),
        "percent_change_24h": _safe_float(quote_usd.get("percent_change_24h"), 0.0),
        # Signals whether we actually matched a real record vs. an all-zero stub
        "_found": bool(token_data),
    }


# ============================================================================
# Dual-pipeline fetchers
#
# RWAs and standard cryptocurrencies come from two entirely different CMC
# data structures (aggregated tokenized RWA arrays vs. standard coin quotes),
# so each pipeline is fetched and normalized in complete isolation, then
# merged only at the very end inside compare_rwa_vs_crypto().
# ============================================================================
async def fetch_rwa_data(symbol: str, api_key: str) -> Dict[str, Any]:
    """
    Pipeline 1: Resolve + fetch an RWA (or specific tokenized RWA) and return
    a normalized dict with tokenized market cap, price, and volume.
    """
    clean_symbol = symbol.strip().upper()

    # Same fast-path as get_rwa_market_quote: reject symbols longer than any
    # real RWA/token symbol before triggering a full issuer-list scan.
    if len(clean_symbol) > 16:
        return {"error": f"RWA identifier '{clean_symbol}' exceeds the maximum supported symbol length of 16 characters."}

    resolved = await resolve_rwa_asset(clean_symbol, api_key=api_key)
    if isinstance(resolved, list):
        resolved = resolved[0] if resolved else {}
    if not isinstance(resolved, dict) or resolved.get("error"):
        return {"error": resolved.get("error", f"Could not resolve RWA '{clean_symbol}'.")}

    rwa_id = resolved.get("rwa_id")
    if rwa_id is None:
        return {"error": f"RWA asset '{clean_symbol}' not found."}

    try:
        rwa_res = await cmc_client.get_rwa_quotes(api_key=api_key, rwa_id=str(rwa_id))
    except Exception as e:
        return {"error": f"Failed fetching RWA asset '{clean_symbol}': {str(e)}"}

    rwa_info = _normalize_rwa_payload(rwa_res)
    specific_token = _extract_token_by_symbol(rwa_info, clean_symbol)
    parent_symbol = rwa_info.get("symbol") or clean_symbol
    parent_name = rwa_info.get("name") or clean_symbol

    if specific_token:
        return {
            "symbol": parent_symbol,
            "name": specific_token.get("name", parent_name),
            "price_usd": _safe_float(specific_token.get("price"), 0.0),
            "market_cap_usd": _safe_float(specific_token.get("market_cap"), 0.0),
            "volume_24h_usd": _safe_float(specific_token.get("volume_24h"), 0.0),
            "asset_label": f"{parent_name} ({parent_symbol})",
            "is_specific_token": True,
        }

    quote = (rwa_info.get("quotes") or [{}])[0]
    return {
        "symbol": parent_symbol,
        "name": parent_name,
        "price_usd": _safe_float(quote.get("average_tokenized_price") or rwa_info.get("average_tokenized_price"), 0.0),
        "market_cap_usd": _safe_float(quote.get("tokenized_market_cap") or rwa_info.get("tokenized_market_cap"), 0.0),
        "volume_24h_usd": _safe_float(quote.get("tokenized_volume_24h") or rwa_info.get("tokenized_volume_24h"), 0.0),
        "asset_label": f"Tokenized {parent_name}",
        "is_specific_token": False,
    }


async def fetch_crypto_data(symbol: str, api_key: str) -> Dict[str, Any]:
    """
    Pipeline 2: Fetch a standard cryptocurrency quote and return a normalized
    dict with price, market cap, and volume — safely handling data[SYMBOL]
    being a list or a dict.
    """
    clean_symbol = symbol.strip().upper()

    try:
        crypto_res = await cmc_client.get_crypto_quotes(api_key=api_key, symbol=clean_symbol)
    except Exception as e:
        return {"error": f"Failed fetching Crypto asset '{clean_symbol}': {str(e)}"}

    quote = extract_crypto_quote(crypto_res, clean_symbol)
    if not quote.get("_found"):
        return {"error": f"Crypto asset '{clean_symbol}' quote data not found."}

    quote.pop("_found", None)
    return quote


# ============================================================================
# Comparison entrypoint — merges the two isolated pipelines
# ============================================================================
async def compare_rwa_vs_crypto(rwa_symbol: str, crypto_symbol: str, api_key: str) -> Dict[str, Any]:
    """Compare a specific RWA token or parent RWA asset against a cryptocurrency."""
    try:
        clean_rwa = rwa_symbol.strip().upper()
        clean_crypto = crypto_symbol.strip().upper()

        rwa_data, crypto_data = await asyncio.gather(
            fetch_rwa_data(clean_rwa, api_key=api_key),
            fetch_crypto_data(clean_crypto, api_key=api_key),
        )

        if rwa_data.get("error"):
            return {"error": rwa_data["error"]}
        if crypto_data.get("error"):
            return {"error": crypto_data["error"]}

        # --- Merge the two isolated pipeline results ---
        rwa_mcap = rwa_data["market_cap_usd"]
        crypto_mcap = crypto_data["market_cap_usd"]
        asset_label = rwa_data["asset_label"]

        mcap_ratio = (
            round(crypto_mcap / rwa_mcap, 2)
            if (rwa_mcap > 0 and crypto_mcap > 0)
            else None
        )

        return {
            "comparison_summary": (
                f"{clean_crypto} market cap is {mcap_ratio}x the size of {asset_label}."
                if mcap_ratio
                else f"Comparison complete for {clean_crypto} and {asset_label}."
            ),
            "rwa_asset": {
                "symbol": rwa_data["symbol"],
                "name": rwa_data["name"],
                "price_usd": rwa_data["price_usd"],
                "market_cap_usd": rwa_mcap,
                "volume_24h_usd": rwa_data["volume_24h_usd"],
                "is_specific_token": rwa_data["is_specific_token"],
            },
            "crypto_asset": {
                "symbol": crypto_data.get("symbol", clean_crypto),
                "name": crypto_data.get("name", clean_crypto),
                "price_usd": crypto_data["price_usd"],
                "market_cap_usd": crypto_mcap,
                "volume_24h_usd": crypto_data["volume_24h_usd"],
                "percent_change_24h": crypto_data["percent_change_24h"],
            },
            "metrics": {
                "market_cap_ratio_crypto_to_rwa": mcap_ratio,
            },
        }

    except Exception as e:
        return {
            "error": f"Comparison between '{rwa_symbol}' and '{crypto_symbol}' failed: {str(e)}"
        }
