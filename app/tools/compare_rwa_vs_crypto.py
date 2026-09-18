import asyncio
from typing import Any, Dict, Optional

from app.cmc.client import cmc_client
from app.tools.resolve_rwa_asset import resolve_rwa_asset


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


async def compare_rwa_vs_crypto(rwa_symbol: str, crypto_symbol: str) -> Dict[str, Any]:
    """Compare a specific RWA token or parent RWA asset against a cryptocurrency."""
    try:
        clean_rwa = rwa_symbol.strip().upper()
        clean_crypto = crypto_symbol.strip().upper()

        # 1. Resolve RWA Metadata
        resolved_rwa = await resolve_rwa_asset(clean_rwa)
        if isinstance(resolved_rwa, list):
            resolved_rwa = resolved_rwa[0] if resolved_rwa else {}
        if not isinstance(resolved_rwa, dict) or resolved_rwa.get("error"):
            return {"error": resolved_rwa.get("error", f"Could not resolve RWA '{clean_rwa}'.")}

        rwa_id = resolved_rwa.get("rwa_id")
        if rwa_id is None:
            return {"error": f"RWA asset '{clean_rwa}' not found."}

        # 2. Fetch Data Concurrently
        rwa_res, crypto_res = await asyncio.gather(
            cmc_client.get_rwa_quotes(rwa_id=str(rwa_id)),
            cmc_client.get_crypto_quotes(symbol=clean_crypto),
            return_exceptions=True,
        )

        if isinstance(rwa_res, Exception):
            return {"error": f"Failed fetching RWA asset '{clean_rwa}': {str(rwa_res)}"}
        if isinstance(crypto_res, Exception):
            return {"error": f"Failed fetching Crypto asset '{clean_crypto}': {str(crypto_res)}"}

        # 3. Parse Crypto Data Safely
        crypto_data = _normalize_crypto_payload(crypto_res, clean_crypto)
        if not crypto_data:
            return {"error": f"Crypto asset '{clean_crypto}' quote data not found."}

        raw_quote = crypto_data.get("quote", crypto_data)
        if isinstance(raw_quote, dict):
            crypto_quote = raw_quote.get("USD", raw_quote)
        else:
            crypto_quote = crypto_data

        crypto_mcap = (
            crypto_quote.get("market_cap")
            or crypto_data.get("market_cap", 0)
            or 0
        )
        crypto_price = (
            crypto_quote.get("price")
            or crypto_data.get("price", 0)
            or 0
        )
        crypto_vol = (
            crypto_quote.get("volume_24h")
            or crypto_data.get("volume_24h", 0)
            or 0
        )
        crypto_change = (
            crypto_quote.get("percent_change_24h")
            or crypto_data.get("percent_change_24h", 0)
            or 0
        )

        # 4. Parse RWA Data (Extract specific child token like PAXG if available)
        rwa_info = _normalize_rwa_payload(rwa_res)
        specific_token = _extract_token_by_symbol(rwa_info, clean_rwa)
        parent_symbol = rwa_info.get("symbol") or clean_rwa
        parent_name = rwa_info.get("name") or clean_rwa

        if specific_token:
            rwa_name = specific_token.get("name", parent_name)
            rwa_mcap = specific_token.get("market_cap") or 0
            rwa_price = specific_token.get("price") or 0
            rwa_volume = specific_token.get("volume_24h") or 0
            asset_label = f"{parent_name} ({parent_symbol})"
            rwa_symbol_out = parent_symbol
        else:
            rwa_name = parent_name
            quote = (rwa_info.get("quotes") or [{}])[0]
            rwa_mcap = quote.get("tokenized_market_cap") or rwa_info.get("tokenized_market_cap") or 0
            rwa_price = quote.get("average_tokenized_price") or rwa_info.get("average_tokenized_price") or 0
            rwa_volume = quote.get("tokenized_volume_24h") or rwa_info.get("tokenized_volume_24h") or 0
            asset_label = f"Tokenized {rwa_name}"
            rwa_symbol_out = parent_symbol

        # 5. Compute Metrics
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
                "symbol": rwa_symbol_out,
                "name": rwa_name,
                "price_usd": rwa_price,
                "market_cap_usd": rwa_mcap,
                "volume_24h_usd": rwa_volume,
                "is_specific_token": specific_token is not None,
            },
            "crypto_asset": {
                "symbol": crypto_data.get("symbol", clean_crypto),
                "name": crypto_data.get("name", clean_crypto),
                "price_usd": crypto_price,
                "market_cap_usd": crypto_mcap,
                "volume_24h_usd": crypto_vol,
                "percent_change_24h": crypto_change,
            },
            "metrics": {
                "market_cap_ratio_crypto_to_rwa": mcap_ratio,
            },
        }

    except Exception as e:
        return {
            "error": f"Comparison between '{rwa_symbol}' and '{crypto_symbol}' failed: {str(e)}"
        }