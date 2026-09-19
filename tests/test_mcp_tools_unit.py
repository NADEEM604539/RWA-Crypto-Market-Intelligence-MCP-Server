"""
Unit tests for MCP tool handlers and utility functions.
Tests asset resolution, payload normalization, and comparison tools.

The fakes below mirror what CoinMarketCap ACTUALLY returns (per the Pro API docs):
  * GET /v5/real-world-assets/quotes/latest?symbol=PAXG  -> HTTP 400 (PAXG is a token, not a parent RWA)
  * GET /v5/real-world-assets/issuers/list               -> {"issuers": [...], "has_more": ...}
  * GET /v5/real-world-assets/issuers?issuer_id=...      -> FLAT issuer object with top-level "tokens"
Earlier versions of these tests faked a `ValueError` and a shape the schema could not represent,
which is why they stayed green while PAXG resolution was broken against the live API.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import pytest

from app.cmc.client import cmc_client
from app.cmc.exceptions import (
    CMCApiError,
    CMCBadRequestError,
    CMCNotFoundError,
    CMCRateLimitError,
    CMCUnauthorizedError,
)
from app.tools.compare_rwa_vs_crypto import compare_rwa_vs_crypto
from app.tools.resolve_rwa_asset import reset_resolver_state, resolve_rwa_asset

DUMMY_API_KEY = "your cmc api key"

GOLD_ASSET: Dict[str, Any] = {
    "rwa_id": 1,
    "symbol": "GOLD",
    "name": "Gold",
    "slug": "gold",
    "asset_type": "commodity",
    "rwa_rank": 1,
    "has_tokens": True,
}

# Deliberately unsorted; the resolver must scan smallest-first and skip empty issuers.
ISSUERS: List[Dict[str, Any]] = [
    {"issuer_id": "big", "name": "Backed Assets", "num_tokens": 1176},
    {"issuer_id": "empty", "name": "Bitget Assets", "num_tokens": 0},
    {"issuer_id": "paxos", "name": "Paxos", "num_tokens": 1},
    {"issuer_id": "tether", "name": "Tether Holdings", "num_tokens": 2},
]

ISSUER_TOKENS: Dict[str, List[Dict[str, Any]]] = {
    "paxos": [{"symbol": "PAXG", "name": "PAX Gold", "crypto_id": 4705, "rwa_id": 1}],
    "tether": [
        {"symbol": "XAUt", "name": "Tether Gold", "crypto_id": 5176, "rwa_id": 1},
        {"symbol": "XAUT0", "name": "Tether Gold Tokens", "crypto_id": 9001, "rwa_id": 1},
    ],
    "big": [{"symbol": "NVDAX", "name": "NVIDIA xStock", "crypto_id": 36992, "rwa_id": 2}],
}

Calls = List[Tuple[str, Any]]


@pytest.fixture(autouse=True)
def _clean_resolver_state() -> Any:
    reset_resolver_state()
    yield
    reset_resolver_state()


def _patch_registry_api(monkeypatch: Any, calls: Calls, issuer_behavior: Any = None) -> None:
    """Patch the CMC client with realistic RWA/issuer behaviour and record every call."""

    async def fake_get_rwa_quotes(api_key: str | None = None, rwa_id: str | None = None, symbol: str | None = None) -> Dict[str, Any]:
        calls.append(("quotes", rwa_id if rwa_id is not None else symbol))
        if symbol is not None:
            if symbol == "GOLD":
                return {"rwa_assets": [dict(GOLD_ASSET)]}
            # Real CMC rejects token tickers on the parent-symbol lookup with HTTP 400.
            raise CMCBadRequestError("Invalid value for \"symbol\"", status_code=400)
        assert rwa_id == "1"
        return {"rwa_assets": [dict(GOLD_ASSET)]}

    async def fake_get_rwa_issuers_list(api_key: str | None = None, limit: int = 100, start: int = 1) -> Dict[str, Any]:
        calls.append(("issuers_list", start))
        return {"issuers": [dict(i) for i in ISSUERS], "total_size": len(ISSUERS), "has_more": False}

    async def fake_get_rwa_issuer(api_key: str | None = None, issuer_id: str | None = None, limit: int = 100, start: int = 1) -> Dict[str, Any]:
        calls.append(("issuer", issuer_id))
        if issuer_behavior is not None:
            issuer_behavior(issuer_id)
        return {"tokens": [dict(t) for t in ISSUER_TOKENS.get(issuer_id or "", [])], "has_more": False}

    monkeypatch.setattr(cmc_client, "get_rwa_quotes", fake_get_rwa_quotes)
    monkeypatch.setattr(cmc_client, "get_rwa_issuers_list", fake_get_rwa_issuers_list)
    monkeypatch.setattr(cmc_client, "get_rwa_issuer", fake_get_rwa_issuer)


def _issuer_calls(calls: Calls) -> List[str]:
    return [arg for kind, arg in calls if kind == "issuer"]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def test_resolve_rwa_asset_accepts_token_symbol(monkeypatch: Any) -> None:
    """Secondary token symbols (e.g. PAXG) resolve to their parent RWA and report the issuer."""
    calls: Calls = []
    _patch_registry_api(monkeypatch, calls)

    result = asyncio.run(resolve_rwa_asset("PAXG", api_key=DUMMY_API_KEY))

    assert "error" not in result
    assert result["symbol"] == "GOLD"
    assert result["resolved_via"] == "token_symbol"
    assert result["rwa_id"] == 1
    assert result["matched_token"]["symbol"] == "PAXG"
    assert result["matched_token"]["issuer_name"] == "Paxos"
    assert result["matched_token"]["crypto_id"] == 4705


def test_resolve_scans_smallest_issuers_first_and_stops_early(monkeypatch: Any) -> None:
    """PAXG must be found without paging through the 1,000+ token issuer or the empty one."""
    calls: Calls = []
    _patch_registry_api(monkeypatch, calls)

    asyncio.run(resolve_rwa_asset("PAXG", api_key=DUMMY_API_KEY))

    assert _issuer_calls(calls) == ["paxos"]


def test_resolve_reuses_registry_for_later_lookups(monkeypatch: Any) -> None:
    calls: Calls = []
    _patch_registry_api(monkeypatch, calls)

    asyncio.run(resolve_rwa_asset("PAXG", api_key=DUMMY_API_KEY))
    second = asyncio.run(resolve_rwa_asset("xaut", api_key=DUMMY_API_KEY))  # case-insensitive
    assert second["symbol"] == "GOLD"
    assert _issuer_calls(calls) == ["paxos", "tether"]

    # XAUT0 was indexed while scanning Tether, so this costs no further issuer calls.
    third = asyncio.run(resolve_rwa_asset("XAUT0", api_key=DUMMY_API_KEY))
    assert third["symbol"] == "GOLD"
    assert _issuer_calls(calls) == ["paxos", "tether"]
    assert [c for c in calls if c[0] == "issuers_list"] == [("issuers_list", 1)]


def test_resolve_parent_symbol_skips_registry(monkeypatch: Any) -> None:
    calls: Calls = []
    _patch_registry_api(monkeypatch, calls)

    result = asyncio.run(resolve_rwa_asset("GOLD", api_key=DUMMY_API_KEY))

    assert result["resolved_via"] == "rwa_symbol"
    assert result["rwa_id"] == 1
    assert _issuer_calls(calls) == []


def test_resolve_unknown_symbol_returns_hint_and_is_remembered(monkeypatch: Any) -> None:
    """Unknown symbols get a non-null hint, and repeating the lookup costs zero API calls."""
    calls: Calls = []
    _patch_registry_api(monkeypatch, calls)

    first = asyncio.run(resolve_rwa_asset("NOPE", api_key=DUMMY_API_KEY))
    assert "not found" in first["error"]
    assert first["hint"]

    scanned = _issuer_calls(calls)
    assert scanned == ["paxos", "tether", "big"]  # every non-empty issuer, smallest first

    asyncio.run(resolve_rwa_asset("NOPE", api_key=DUMMY_API_KEY))
    assert _issuer_calls(calls) == scanned
    assert len([c for c in calls if c[0] == "issuers_list"]) == 1


def test_resolve_reports_real_failures_instead_of_not_found(monkeypatch: Any) -> None:
    """A bad API key must not be disguised as 'symbol not found'."""
    async def fake_get_rwa_quotes(api_key: str | None = None, rwa_id: str | None = None, symbol: str | None = None) -> Dict[str, Any]:
        raise CMCUnauthorizedError("Invalid API key", status_code=401)

    monkeypatch.setattr(cmc_client, "get_rwa_quotes", fake_get_rwa_quotes)

    result = asyncio.run(resolve_rwa_asset("PAXG", api_key=DUMMY_API_KEY))

    assert "Failed to resolve" in result["error"]
    assert "Invalid API key" in result["error"]
    assert "not found" not in result["error"]


def test_resolve_retries_issuer_after_transient_failure(monkeypatch: Any) -> None:
    """A 429 while scanning must not permanently lose that issuer from the scan."""
    calls: Calls = []
    state = {"failed_once": False}

    def flaky(issuer_id: str | None) -> None:
        if issuer_id == "paxos" and not state["failed_once"]:
            state["failed_once"] = True
            raise CMCRateLimitError("Too many requests", status_code=429)

    _patch_registry_api(monkeypatch, calls, issuer_behavior=flaky)

    first = asyncio.run(resolve_rwa_asset("PAXG", api_key=DUMMY_API_KEY))
    assert "error" in first

    second = asyncio.run(resolve_rwa_asset("PAXG", api_key=DUMMY_API_KEY))
    assert second["symbol"] == "GOLD"


# ---------------------------------------------------------------------------
# Schema / client regressions (these need pydantic + httpx, i.e. the real app env)
# ---------------------------------------------------------------------------
def test_issuer_detail_schema_keeps_tokens() -> None:
    """Regression: the flat single-issuer payload used to lose `tokens` during validation."""
    from app.cmc.schemas import RWAIssuerResponse

    payload = {
        "data": {
            "name": "Paxos",
            "website": "https://www.paxos.com/",
            "logo": None,
            "tokens": [{"name": "PAX Gold", "symbol": "PAXG", "crypto_id": 4705, "rwa_id": 1}],
            "issuer_id": "68904c24abae9b5b9fb35815",
            "num_tokens": 1,
            "total_size": 1,
            "has_more": False,
        },
        "status": {"error_code": 0},
    }

    data = RWAIssuerResponse.model_validate(payload).model_dump(mode="python")["data"]

    assert data["tokens"][0]["symbol"] == "PAXG"
    assert data["tokens"][0]["rwa_id"] == 1
    assert data["tokens"][0]["crypto_id"] == 4705


def test_only_transient_errors_are_retried() -> None:
    """Regression: 400/401/404 used to be retried with backoff, wasting credits and seconds."""
    import httpx

    from app.cmc.client import _is_retryable

    assert _is_retryable(CMCRateLimitError("slow down", status_code=429))
    assert _is_retryable(CMCApiError("upstream", status_code=503))
    assert _is_retryable(httpx.ConnectError("network down"))

    assert not _is_retryable(CMCBadRequestError("bad symbol", status_code=400))
    assert not _is_retryable(CMCUnauthorizedError("bad key", status_code=401))
    assert not _is_retryable(CMCNotFoundError("nothing", status_code=404))


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
BTC_PAYLOAD = {
    "BTC": {
        "id": 1,
        "symbol": "BTC",
        "name": "Bitcoin",
        "quote": {
            "USD": {
                "price": 60000,
                "market_cap": 1200000000000,
                "volume_24h": 50000000000,
                "percent_change_24h": 2.5,
            }
        },
    }
}


def _gold_quote_payload() -> Dict[str, Any]:
    return {
        "rwa_assets": [
            {
                **GOLD_ASSET,
                "quotes": [
                    {
                        "average_tokenized_price": 4366.29,
                        "tokenized_market_cap": 4711934921.0,
                        "tokenized_volume_24h": 131404543.58,
                    }
                ],
                "tokens": [
                    {
                        "symbol": "PAXG",
                        "name": "PAX Gold",
                        "price": 4364.956152,
                        "crypto_id": 4705,
                        "issuer_name": "Paxos",
                        "market_cap": 1896570687.52,
                        "volume_24h": 62944583.45,
                    },
                    {
                        "symbol": "XAUt",
                        "name": "Tether Gold",
                        "price": 4373.4013,
                        "crypto_id": 5176,
                        "issuer_name": "Tether Holdings",
                        "market_cap": 2723857803.42,
                        "volume_24h": 67102151.14,
                    },
                ],
            }
        ]
    }


def _patch_compare_api(monkeypatch: Any, paxg_crypto_payload: Dict[str, Any] | None) -> None:
    calls: Calls = []
    _patch_registry_api(monkeypatch, calls)

    async def fake_get_rwa_quotes(api_key: str | None = None, rwa_id: str | None = None, symbol: str | None = None) -> Dict[str, Any]:
        if rwa_id == "1":
            return _gold_quote_payload()
        if symbol == "GOLD":
            return {"rwa_assets": [dict(GOLD_ASSET)]}
        raise CMCBadRequestError("Invalid value for \"symbol\"", status_code=400)

    async def fake_get_crypto_quotes(api_key: str | None = None, symbol: str | None = None) -> Dict[str, Any]:
        if symbol == "BTC":
            return BTC_PAYLOAD
        if symbol == "PAXG" and paxg_crypto_payload is not None:
            return paxg_crypto_payload
        raise CMCBadRequestError("Invalid value for \"symbol\"", status_code=400)

    monkeypatch.setattr(cmc_client, "get_rwa_quotes", fake_get_rwa_quotes)
    monkeypatch.setattr(cmc_client, "get_crypto_quotes", fake_get_crypto_quotes)


def test_compare_rwa_vs_crypto_accepts_tokenized_rwa_symbol(monkeypatch: Any) -> None:
    """A token symbol yields the token's own slice (not the GOLD aggregate), with V/MC and 24h change."""
    _patch_compare_api(
        monkeypatch,
        {
            "PAXG": {
                "id": 4705,
                "symbol": "PAXG",
                "name": "PAX Gold",
                "quote": {"USD": {"price": 4364.96, "percent_change_24h": 0.42}},
            }
        },
    )

    result = asyncio.run(compare_rwa_vs_crypto("PAXG", "BTC", api_key=DUMMY_API_KEY))

    assert "error" not in result
    assert result["rwa_asset"]["symbol"] == "GOLD"  # backward compatible: parent symbol
    assert result["crypto_asset"]["symbol"] == "BTC"

    rwa = result["rwa_asset"]
    assert rwa["is_specific_token"] is True
    assert rwa["token_symbol"] == "PAXG"
    assert rwa["parent_symbol"] == "GOLD"
    assert rwa["issuer_name"] == "Paxos"
    assert rwa["market_cap_usd"] == pytest.approx(1896570687.52)
    assert rwa["percent_change_24h"] == pytest.approx(0.42)
    assert rwa["volume_to_market_cap_ratio"] == pytest.approx(0.033189, abs=1e-6)
    assert result["crypto_asset"]["volume_to_market_cap_ratio"] == pytest.approx(0.041667, abs=1e-6)
    assert result["metrics"]["volume_to_market_cap_ratio_rwa"] == rwa["volume_to_market_cap_ratio"]
    assert result["metrics"]["notes"] == []


def test_compare_discards_change_when_crypto_id_mismatches(monkeypatch: Any) -> None:
    """A different coin sharing the ticker must never supply the RWA token's 24h change."""
    _patch_compare_api(
        monkeypatch,
        {
            "PAXG": {
                "id": 999999,
                "symbol": "PAXG",
                "name": "Some Other PAXG",
                "quote": {"USD": {"percent_change_24h": 55.0}},
            }
        },
    )

    result = asyncio.run(compare_rwa_vs_crypto("PAXG", "BTC", api_key=DUMMY_API_KEY))

    assert result["rwa_asset"]["is_specific_token"] is True
    assert result["rwa_asset"]["percent_change_24h"] is None
    assert result["metrics"]["notes"]  # tells the caller why it is missing


def test_compare_aggregate_never_fabricates_a_price_change(monkeypatch: Any) -> None:
    _patch_compare_api(monkeypatch, None)

    result = asyncio.run(compare_rwa_vs_crypto("GOLD", "BTC", api_key=DUMMY_API_KEY))

    assert result["rwa_asset"]["is_specific_token"] is False
    assert result["rwa_asset"]["percent_change_24h"] is None  # None, not a made-up 0.0
    assert result["metrics"]["notes"]


def test_compare_rwa_vs_crypto_handles_list_payloads(monkeypatch: Any) -> None:
    """Payload handler gracefully parses list-formatted API responses."""
    calls: Calls = []
    _patch_registry_api(monkeypatch, calls)

    async def fake_get_rwa_quotes(api_key: str | None = None, rwa_id: str | None = None, symbol: str | None = None) -> List[Dict[str, Any]]:
        if rwa_id == "1":
            return [
                {
                    **GOLD_ASSET,
                    "quotes": [
                        {
                            "average_tokenized_price": 3000,
                            "tokenized_market_cap": 1000000000,
                            "tokenized_volume_24h": 50000000,
                        }
                    ],
                    "tokens": [{"symbol": "PAXG", "name": "PAX Gold"}],
                }
            ]
        raise CMCBadRequestError("Invalid value for \"symbol\"", status_code=400)

    async def fake_get_crypto_quotes(api_key: str | None = None, symbol: str | None = None) -> Dict[str, Any]:
        if symbol == "BTC":
            return BTC_PAYLOAD
        raise CMCBadRequestError("Invalid value for \"symbol\"", status_code=400)

    monkeypatch.setattr(cmc_client, "get_rwa_quotes", fake_get_rwa_quotes)
    monkeypatch.setattr(cmc_client, "get_crypto_quotes", fake_get_crypto_quotes)

    result = asyncio.run(compare_rwa_vs_crypto("PAXG", "BTC", api_key=DUMMY_API_KEY))

    assert "error" not in result
    assert result["rwa_asset"]["symbol"] == "GOLD"
    assert result["crypto_asset"]["symbol"] == "BTC"
    # This token record carries no market cap, so V/MC must be None rather than a fabricated 0.
    assert result["rwa_asset"]["volume_to_market_cap_ratio"] is None
