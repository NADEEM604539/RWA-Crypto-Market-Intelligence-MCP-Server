"""
Extended unit tests covering the files the original suite didn't touch:
  - app/utils/cache.py        (TTLCache, AsyncRateLimiter)
  - app/auth/auth.py          (RateLimiter, authenticate_and_rate_limit)
  - app/tools/get_global_market_metrics.py
  - app/tools/get_rwa_issuers_info.py
  - app/tools/get_rwa_market_quote.py (unit-conversion and edge-case paths
    not already exercised via compare_rwa_vs_crypto in test_mcp_tools_unit.py)

Every test below targets a real, exercisable behaviour documented in the
source -- sliding-window rate limiting, TTL expiry, LRU-ish eviction, the
gram-vs-troy-ounce heuristic, the "known but untracked" ticker hint, and
the 16-char fast-path rejection -- not just "does it return a dict".
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from app.cmc.client import cmc_client
from app.cmc.exceptions import CMCBadRequestError
from app.utils.cache import AsyncRateLimiter, TTLCache, shared_cache

Calls = List[Tuple[str, Any]]


@pytest.fixture(autouse=True)
def _clean_shared_cache() -> Any:
    """The tools under test share a module-level TTLCache singleton, so
    without this, a cached result from one test would leak into the next
    and silently hide a real bug (e.g. a test that should have triggered
    a fresh API call instead getting a stale hit)."""
    asyncio.run(shared_cache.clear())
    yield
    asyncio.run(shared_cache.clear())


# ---------------------------------------------------------------------------
# TTLCache
# ---------------------------------------------------------------------------
def test_ttlcache_miss_returns_none() -> None:
    cache = TTLCache()
    assert asyncio.run(cache.get("nope")) is None


def test_ttlcache_set_then_get_roundtrips() -> None:
    cache = TTLCache(default_ttl_seconds=60.0)

    async def run() -> Any:
        await cache.set("k", {"v": 1})
        return await cache.get("k")

    assert asyncio.run(run()) == {"v": 1}


def test_ttlcache_expires_after_ttl(monkeypatch: Any) -> None:
    """An entry must stop being served the instant its TTL has elapsed,
    not just 'eventually' -- otherwise stale market data gets served."""
    fake_now = {"t": 1000.0}
    monkeypatch.setattr("app.utils.cache.time.monotonic", lambda: fake_now["t"])
    cache = TTLCache()

    async def run() -> Tuple[Any, Any]:
        await cache.set("k", "value", ttl_seconds=10.0)
        before = await cache.get("k")
        fake_now["t"] += 10.0  # exactly at expiry boundary
        after = await cache.get("k")
        return before, after

    before, after = asyncio.run(run())
    assert before == "value"
    assert after is None  # is_expired uses >=, so the boundary itself has expired


def test_ttlcache_evicts_entry_closest_to_expiry_when_full() -> None:
    """With max_entries=2, adding a 3rd entry must evict whichever existing
    entry expires soonest -- not just the oldest by insertion order -- so a
    long-lived entry (e.g. the issuer list, cached 5 min) doesn't get
    thrown out to make room for a short-lived one."""
    cache = TTLCache(max_entries=2)

    async def run() -> Dict[str, Any]:
        await cache.set("long_lived", "A", ttl_seconds=1000.0)
        await cache.set("short_lived", "B", ttl_seconds=1.0)
        await cache.set("newcomer", "C", ttl_seconds=100.0)
        return {
            "long_lived": await cache.get("long_lived"),
            "short_lived": await cache.get("short_lived"),
            "newcomer": await cache.get("newcomer"),
        }

    result = asyncio.run(run())
    assert result["long_lived"] == "A"
    assert result["short_lived"] is None  # evicted: nearest to expiry
    assert result["newcomer"] == "C"


def test_ttlcache_get_or_set_only_calls_factory_once(monkeypatch: Any) -> None:
    calls = {"n": 0}
    cache = TTLCache()

    def factory() -> str:
        calls["n"] += 1
        return "computed"

    async def run() -> Tuple[Any, Any]:
        first = await cache.get_or_set("k", factory)
        second = await cache.get_or_set("k", factory)
        return first, second

    first, second = asyncio.run(run())
    assert first == second == "computed"
    assert calls["n"] == 1  # second call must be a cache hit, not a recompute


def test_ttlcache_get_or_set_awaits_async_factory() -> None:
    cache = TTLCache()

    async def factory() -> str:
        return "async-computed"

    assert asyncio.run(cache.get_or_set("k", factory)) == "async-computed"


def test_ttlcache_delete_and_clear() -> None:
    cache = TTLCache()

    async def run() -> Tuple[Any, Any]:
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.delete("a")
        after_delete = (await cache.get("a"), await cache.get("b"))
        await cache.clear()
        after_clear = (await cache.get("a"), await cache.get("b"))
        return after_delete, after_clear

    after_delete, after_clear = asyncio.run(run())
    assert after_delete == (None, 2)
    assert after_clear == (None, None)


# ---------------------------------------------------------------------------
# AsyncRateLimiter
# ---------------------------------------------------------------------------
def test_async_rate_limiter_rejects_non_positive_max_calls() -> None:
    with pytest.raises(ValueError):
        AsyncRateLimiter(max_calls=0)


def test_async_rate_limiter_allows_calls_up_to_the_limit_without_waiting(monkeypatch: Any) -> None:
    sleep_calls = {"n": 0}

    async def fake_sleep(_: float) -> None:
        sleep_calls["n"] += 1

    monkeypatch.setattr("app.utils.cache.asyncio.sleep", fake_sleep)
    limiter = AsyncRateLimiter(max_calls=3, period_seconds=60.0)

    async def run() -> None:
        for _ in range(3):
            await limiter.acquire()

    asyncio.run(run())
    assert sleep_calls["n"] == 0  # 3 calls within a 3-call budget must never sleep


def test_async_rate_limiter_waits_once_window_is_full(monkeypatch: Any) -> None:
    """The 4th call within the window must wait, proving this is a real
    throttle and not just a counter -- this is what keeps the server from
    hammering CMC and burning through 429s."""
    fake_now = {"t": 0.0}
    monkeypatch.setattr("app.utils.cache.time.monotonic", lambda: fake_now["t"])

    sleep_durations: List[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_durations.append(seconds)
        fake_now["t"] += seconds  # simulate time actually passing

    monkeypatch.setattr("app.utils.cache.asyncio.sleep", fake_sleep)
    limiter = AsyncRateLimiter(max_calls=2, period_seconds=60.0)

    async def run() -> None:
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()  # 3rd call must wait for the window to free up

    asyncio.run(run())
    assert len(sleep_durations) >= 1
    assert all(d > 0 for d in sleep_durations)


def test_async_rate_limiter_used_as_context_manager() -> None:
    limiter = AsyncRateLimiter(max_calls=1, period_seconds=60.0)

    async def run() -> bool:
        async with limiter:
            return True

    assert asyncio.run(run()) is True


# ---------------------------------------------------------------------------
# auth.py -- RateLimiter (per-API-key sliding window)
# ---------------------------------------------------------------------------
def _fresh_rate_limiter(monkeypatch: Any, rpm: int) -> Tuple[Any, Dict[str, float]]:
    from app.auth.auth import RateLimiter

    fake_now = {"t": 1_000_000.0}
    monkeypatch.setattr("app.auth.auth.time.time", lambda: fake_now["t"])
    return RateLimiter(requests_per_minute=rpm), fake_now


def test_rate_limiter_allows_requests_up_to_rpm(monkeypatch: Any) -> None:
    limiter, _ = _fresh_rate_limiter(monkeypatch, rpm=3)

    async def run() -> List[bool]:
        return [(await limiter.is_allowed("key-a"))[0] for _ in range(3)]

    assert asyncio.run(run()) == [True, True, True]


def test_rate_limiter_blocks_the_request_beyond_rpm_with_positive_retry_after(monkeypatch: Any) -> None:
    limiter, _ = _fresh_rate_limiter(monkeypatch, rpm=2)

    async def run() -> Tuple[bool, int]:
        await limiter.is_allowed("key-a")
        await limiter.is_allowed("key-a")
        return await limiter.is_allowed("key-a")  # 3rd request, over budget

    allowed, retry_after = asyncio.run(run())
    assert allowed is False
    assert retry_after >= 1  # must never tell a caller to retry in 0 or negative seconds


def test_rate_limiter_tracks_each_api_key_independently(monkeypatch: Any) -> None:
    """One caller hitting their limit must never block a different caller
    using a different key -- otherwise one noisy client DoSes everyone else."""
    limiter, _ = _fresh_rate_limiter(monkeypatch, rpm=1)

    async def run() -> Tuple[bool, bool]:
        await limiter.is_allowed("key-a")
        blocked_a = (await limiter.is_allowed("key-a"))[0]
        allowed_b = (await limiter.is_allowed("key-b"))[0]
        return blocked_a, allowed_b

    blocked_a, allowed_b = asyncio.run(run())
    assert blocked_a is False
    assert allowed_b is True


def test_rate_limiter_window_slides_and_forgets_old_requests(monkeypatch: Any) -> None:
    limiter, fake_now = _fresh_rate_limiter(monkeypatch, rpm=1)

    async def run() -> Tuple[bool, bool]:
        first = (await limiter.is_allowed("key-a"))[0]
        blocked = (await limiter.is_allowed("key-a"))[0]
        fake_now["t"] += 60.1  # push the first request just outside the 60s window
        allowed_again = (await limiter.is_allowed("key-a"))[0]
        return blocked, allowed_again

    blocked, allowed_again = asyncio.run(run())
    assert blocked is False
    assert allowed_again is True  # old timestamp aged out, budget is back


# ---------------------------------------------------------------------------
# auth.py -- authenticate_and_rate_limit
# ---------------------------------------------------------------------------
def _async_returns(value: Any):
    async def _inner(*args: Any, **kwargs: Any) -> Any:
        return value
    return _inner


def test_authenticate_missing_key_returns_unauthorized_payload() -> None:
    from app.auth.auth import authenticate_and_rate_limit

    api_key, error = asyncio.run(authenticate_and_rate_limit({}))

    assert api_key is None
    payload = json.loads(error)
    assert payload["error"] == "Unauthorized"


def test_authenticate_extracts_key_from_bearer_authorization_header(monkeypatch: Any) -> None:
    from app import auth as auth_module
    from app.auth.auth import authenticate_and_rate_limit

    monkeypatch.setattr(auth_module.auth.rate_limiter, "is_allowed", _async_returns((True, 0)))
    monkeypatch.setattr(auth_module.auth, "verify_cmc_api_key", _async_returns((True, "ok")))

    api_key, error = asyncio.run(
        authenticate_and_rate_limit({"authorization": "Bearer my-real-key"})
    )

    assert error is None
    assert api_key == "my-real-key"


def test_authenticate_rate_limited_returns_429_style_payload(monkeypatch: Any) -> None:
    from app import auth as auth_module
    from app.auth.auth import authenticate_and_rate_limit

    monkeypatch.setattr(auth_module.auth.rate_limiter, "is_allowed", _async_returns((False, 17)))

    api_key, error = asyncio.run(
        authenticate_and_rate_limit({"x-cmc_pro_api_key": "some-key"})
    )

    assert api_key is None
    payload = json.loads(error)
    assert payload["error"] == "Too Many Requests"
    assert payload["retry_after"] == 17


def test_authenticate_invalid_key_is_rejected_before_reaching_the_tool(monkeypatch: Any) -> None:
    from app import auth as auth_module
    from app.auth.auth import authenticate_and_rate_limit

    monkeypatch.setattr(auth_module.auth.rate_limiter, "is_allowed", _async_returns((True, 0)))
    monkeypatch.setattr(
        auth_module.auth, "verify_cmc_api_key", _async_returns((False, "Invalid or unauthorized CoinMarketCap API Key"))
    )

    api_key, error = asyncio.run(
        authenticate_and_rate_limit({"x-cmc_pro_api_key": "bad-key"})
    )

    assert api_key is None
    payload = json.loads(error)
    assert payload["error"] == "Unauthorized"
    assert "Invalid or unauthorized" in payload["message"]


def test_authenticate_success_returns_the_key_and_no_error(monkeypatch: Any) -> None:
    from app import auth as auth_module
    from app.auth.auth import authenticate_and_rate_limit

    monkeypatch.setattr(auth_module.auth.rate_limiter, "is_allowed", _async_returns((True, 0)))
    monkeypatch.setattr(auth_module.auth, "verify_cmc_api_key", _async_returns((True, "Key valid")))

    api_key, error = asyncio.run(
        authenticate_and_rate_limit({"x-cmc_pro_api_key": "good-key"})
    )

    assert api_key == "good-key"
    assert error is None


# ---------------------------------------------------------------------------
# get_global_market_metrics
# ---------------------------------------------------------------------------
def test_get_global_market_metrics_maps_fields_correctly(monkeypatch: Any) -> None:
    from app.tools.get_global_market_metrics import get_global_market_metrics

    async def fake_get_global_metrics(api_key: str) -> Dict[str, Any]:
        return {
            "btc_dominance": 58.79,
            "eth_dominance": 11.57,
            "active_cryptocurrencies": 8164,
            "quote": {
                "USD": {
                    "total_market_cap": 2_777_826_857_730.9,
                    "total_volume_24h": 71_949_388_586.99,
                    "last_updated": "2026-09-19T23:33:59.999Z",
                }
            },
        }

    monkeypatch.setattr(cmc_client, "get_global_metrics", fake_get_global_metrics)

    result = asyncio.run(get_global_market_metrics(api_key="k"))

    assert result["btc_dominance"] == 58.79
    assert result["total_market_cap_usd"] == 2_777_826_857_730.9
    assert result["total_volume_24h_usd"] == 71_949_388_586.99


def test_get_global_market_metrics_is_cached_between_calls(monkeypatch: Any) -> None:
    """Global metrics are intentionally cached for 2 minutes (it's a macro
    snapshot, not a per-request live quote) -- a second call in that window
    must not hit the upstream client again."""
    from app.tools.get_global_market_metrics import get_global_market_metrics

    call_count = {"n": 0}

    async def fake_get_global_metrics(api_key: str) -> Dict[str, Any]:
        call_count["n"] += 1
        return {"btc_dominance": 50.0, "eth_dominance": 10.0, "active_cryptocurrencies": 1, "quote": {"USD": {}}}

    monkeypatch.setattr(cmc_client, "get_global_metrics", fake_get_global_metrics)

    asyncio.run(get_global_market_metrics(api_key="k"))
    asyncio.run(get_global_market_metrics(api_key="k"))

    assert call_count["n"] == 1


def test_get_global_market_metrics_failure_returns_error_dict_not_an_exception(monkeypatch: Any) -> None:
    from app.tools.get_global_market_metrics import get_global_market_metrics

    async def fake_get_global_metrics(api_key: str) -> Dict[str, Any]:
        raise CMCBadRequestError("upstream exploded", status_code=400)

    monkeypatch.setattr(cmc_client, "get_global_metrics", fake_get_global_metrics)

    result = asyncio.run(get_global_market_metrics(api_key="k"))

    assert "error" in result
    assert "Failed to fetch global market metrics" in result["error"]


# ---------------------------------------------------------------------------
# get_rwa_issuers_info
# ---------------------------------------------------------------------------
def test_get_rwa_issuers_info_formats_and_counts_issuers(monkeypatch: Any) -> None:
    from app.tools.get_rwa_issuers_info import get_rwa_issuers_info

    async def fake_get_rwa_issuers_list(api_key: str, limit: int = 100, start: int = 1) -> Dict[str, Any]:
        return {
            "total_size": 25,
            "issuers": [
                {"issuer_id": "68904cceabae9b5b9fb35839", "name": "Comtech Gold", "website": "https://www.comtechgold.com/", "num_tokens": 1},
                {"issuer_id": "6878977dcbbf471de3366e85", "name": "Backed Assets", "website": "https://assets.backed.fi/", "num_tokens": 1176},
            ],
        }

    monkeypatch.setattr(cmc_client, "get_rwa_issuers_list", fake_get_rwa_issuers_list)

    result = asyncio.run(get_rwa_issuers_info(api_key="k", limit=10))

    assert result["total_issuers_tracked"] == 25
    assert result["count_returned"] == 2
    assert result["issuers"][1]["name"] == "Backed Assets"
    assert result["issuers"][1]["num_tokens"] == 1176


def test_get_rwa_issuers_info_caches_separately_per_limit(monkeypatch: Any) -> None:
    """limit=10 and limit=50 are different requests and must not share a
    cache entry, or a caller asking for 50 could silently get back 10."""
    from app.tools.get_rwa_issuers_info import get_rwa_issuers_info

    calls: List[int] = []

    async def fake_get_rwa_issuers_list(api_key: str, limit: int = 100, start: int = 1) -> Dict[str, Any]:
        calls.append(limit)
        return {"total_size": 1, "issuers": [{"issuer_id": "x", "name": "X", "website": None, "num_tokens": 1}]}

    monkeypatch.setattr(cmc_client, "get_rwa_issuers_list", fake_get_rwa_issuers_list)

    asyncio.run(get_rwa_issuers_info(api_key="k", limit=10))
    asyncio.run(get_rwa_issuers_info(api_key="k", limit=10))  # should be a cache hit
    asyncio.run(get_rwa_issuers_info(api_key="k", limit=50))  # different limit, real call

    assert calls == [10, 50]


def test_get_rwa_issuers_info_failure_returns_error_dict(monkeypatch: Any) -> None:
    from app.tools.get_rwa_issuers_info import get_rwa_issuers_info

    async def fake_get_rwa_issuers_list(api_key: str, limit: int = 100, start: int = 1) -> Dict[str, Any]:
        raise CMCBadRequestError("boom", status_code=400)

    monkeypatch.setattr(cmc_client, "get_rwa_issuers_list", fake_get_rwa_issuers_list)

    result = asyncio.run(get_rwa_issuers_info(api_key="k"))

    assert "error" in result
    assert "Failed to fetch RWA issuers info" in result["error"]


# ---------------------------------------------------------------------------
# get_rwa_market_quote -- registry fakes (same shape as test_mcp_tools_unit.py)
# ---------------------------------------------------------------------------
GOLD_ASSET: Dict[str, Any] = {
    "rwa_id": 1,
    "symbol": "GOLD",
    "name": "Gold",
    "slug": "gold",
    "asset_type": "commodity",
    "rwa_rank": 1,
    "has_tokens": True,
}

ISSUERS: List[Dict[str, Any]] = [
    {"issuer_id": "paxos", "name": "Paxos", "num_tokens": 1},
]

ISSUER_TOKENS: Dict[str, List[Dict[str, Any]]] = {
    "paxos": [{"symbol": "PAXG", "name": "PAX Gold", "crypto_id": 4705, "rwa_id": 1}],
}


def _gold_quote_payload_with_gram_and_ounce_tokens() -> Dict[str, Any]:
    """One token priced in the gram convention (Comtech Gold, ~$139/gram)
    and one priced in the troy-ounce convention (PAXG, ~$4365/oz) -- this is
    the exact pair the gram/troy-ounce heuristic exists to disambiguate."""
    return {
        "rwa_assets": [
            {
                **GOLD_ASSET,
                "quotes": [{"average_tokenized_price": 4366.29, "tokenized_market_cap": 4.7e9, "tokenized_volume_24h": 1.3e8}],
                "tokens": [
                    {"symbol": "PAXG", "name": "PAX Gold", "price": 4365.28, "issuer_name": "Paxos", "market_cap": 1.9e9, "volume_24h": 6.2e7},
                    {"symbol": "CGO", "name": "Comtech Gold", "price": 138.95, "issuer_name": "Comtech Gold", "market_cap": 1.9e7, "volume_24h": 9.2e5},
                ],
            }
        ]
    }


def _patch_market_quote_registry(monkeypatch: Any) -> None:
    async def fake_get_rwa_quotes(api_key: Optional[str] = None, rwa_id: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
        if symbol == "GOLD" or rwa_id == "1":
            return _gold_quote_payload_with_gram_and_ounce_tokens()
        raise CMCBadRequestError("Invalid value for \"symbol\"", status_code=400)

    async def fake_get_rwa_issuers_list(api_key: Optional[str] = None, limit: int = 100, start: int = 1) -> Dict[str, Any]:
        return {"issuers": [dict(i) for i in ISSUERS], "total_size": len(ISSUERS), "has_more": False}

    async def fake_get_rwa_issuer(api_key: Optional[str] = None, issuer_id: Optional[str] = None, limit: int = 100, start: int = 1) -> Dict[str, Any]:
        return {"tokens": [dict(t) for t in ISSUER_TOKENS.get(issuer_id or "", [])], "has_more": False}

    monkeypatch.setattr(cmc_client, "get_rwa_quotes", fake_get_rwa_quotes)
    monkeypatch.setattr(cmc_client, "get_rwa_issuers_list", fake_get_rwa_issuers_list)
    monkeypatch.setattr(cmc_client, "get_rwa_issuer", fake_get_rwa_issuer)


@pytest.fixture(autouse=True)
def _clean_resolver_state_for_market_quote() -> Any:
    """get_rwa_market_quote() calls resolve_rwa_asset() internally, which
    has its own module-level registry cache -- reset it same as the
    original suite does, so these tests don't depend on run order."""
    from app.tools.resolve_rwa_asset import reset_resolver_state

    reset_resolver_state()
    yield
    reset_resolver_state()


def test_get_rwa_market_quote_annotates_gram_vs_troy_ounce_correctly(monkeypatch: Any) -> None:
    from app.tools.get_rwa_market_quote import get_rwa_market_quote

    _patch_market_quote_registry(monkeypatch)

    result = asyncio.run(get_rwa_market_quote("GOLD", api_key="k"))

    tokens_by_symbol = {t["symbol"]: t for t in result["tokens"]}
    assert tokens_by_symbol["CGO"]["unit"] == "gram"
    assert tokens_by_symbol["CGO"]["normalized_price_per_oz_usd"] == pytest.approx(138.95 * 31.1034768, abs=0.01)
    assert tokens_by_symbol["PAXG"]["unit"] == "troy_ounce"
    assert tokens_by_symbol["PAXG"]["normalized_price_per_oz_usd"] == pytest.approx(4365.28, abs=0.01)


def test_get_rwa_market_quote_surfaces_the_specifically_requested_token(monkeypatch: Any) -> None:
    from app.tools.get_rwa_market_quote import get_rwa_market_quote

    _patch_market_quote_registry(monkeypatch)

    result = asyncio.run(get_rwa_market_quote("PAXG", api_key="k"))

    assert result["resolved"] is True
    assert result["resolved_via"] == "token_symbol"
    assert result["requested_token"]["symbol"] == "PAXG"
    assert result["requested_token"]["unit"] == "troy_ounce"


def test_get_rwa_market_quote_rejects_identifiers_over_16_chars_without_an_api_round_trip(monkeypatch: Any) -> None:
    """This must short-circuit before touching resolve_rwa_asset/issuer
    scanning entirely -- the whole point is avoiding a wasted API round
    trip on input that can never resolve."""
    from app.tools.get_rwa_market_quote import get_rwa_market_quote

    calls: Calls = []

    async def fake_get_rwa_quotes(api_key: Optional[str] = None, rwa_id: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
        calls.append(("quotes", symbol or rwa_id))
        if symbol == "GOLD" or rwa_id == "1":
            return _gold_quote_payload_with_gram_and_ounce_tokens()
        raise CMCBadRequestError("bad", status_code=400)

    async def fake_get_rwa_issuers_list(api_key: Optional[str] = None, limit: int = 100, start: int = 1) -> Dict[str, Any]:
        calls.append(("issuers_list", None))
        return {"issuers": [], "total_size": 0, "has_more": False}

    monkeypatch.setattr(cmc_client, "get_rwa_quotes", fake_get_rwa_quotes)
    monkeypatch.setattr(cmc_client, "get_rwa_issuers_list", fake_get_rwa_issuers_list)

    overlong = "X" * 17
    result = asyncio.run(get_rwa_market_quote(overlong, api_key="k"))

    assert result["resolved"] is False
    assert "exceeds the maximum supported symbol length" in result["error"]
    assert ("issuers_list", None) not in calls  # no issuer scan was triggered


def test_get_rwa_market_quote_known_untracked_ticker_gets_an_honest_hint(monkeypatch: Any) -> None:
    """BUIDL/OUSG/USDY must never look like a lookup bug -- the tool should
    say plainly that the data isn't tracked yet, not just 'not found'."""
    from app.tools.get_rwa_market_quote import get_rwa_market_quote

    _patch_market_quote_registry(monkeypatch)  # no BUIDL anywhere in this registry

    result = asyncio.run(get_rwa_market_quote("BUIDL", api_key="k"))

    assert result["resolved"] is False
    assert "not currently indexed by this data source" in result["hint"]


def test_get_rwa_market_quote_numeric_identifier_is_used_as_rwa_id_directly(monkeypatch: Any) -> None:
    """A purely numeric identifier must skip symbol resolution entirely and
    be treated as an rwa_id -- resolved_via should reflect that shortcut."""
    from app.tools.get_rwa_market_quote import get_rwa_market_quote

    _patch_market_quote_registry(monkeypatch)

    result = asyncio.run(get_rwa_market_quote("1", api_key="k"))

    assert result["resolved"] is True
    assert result["resolved_via"] == "rwa_id"
    assert result["rwa_id"] == 1
