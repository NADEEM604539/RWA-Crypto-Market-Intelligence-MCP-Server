import asyncio
from typing import Any, Dict, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel

from app.cmc.exceptions import (
    CMCApiError,
    CMCUnauthorizedError,
    CMCRateLimitError,
    raise_for_status,
)
from app.cmc.schemas import (
    CryptoQuotesResponse,
    GlobalMetricsResponse,
    RWAIssuerResponse,
    RWAQuotesResponse,
    RWAIssuersResponse,
)
from app.config import settings
from app.utils.cache import AsyncRateLimiter, TTLCache

T = TypeVar("T", bound=BaseModel)


def _is_retryable(exc: BaseException) -> bool:
    """Retry only transient failures: network errors, HTTP 429 and 5xx.

    4xx client errors (400 unknown symbol, 401/403 bad key, 404) fail identically
    on every retry, so retrying them only burns rate-limit budget and API credits
    and adds seconds of backoff before the caller's fallback logic can run.
    """
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, CMCRateLimitError):
        return True
    if isinstance(exc, CMCApiError):
        return exc.status_code >= 500
    return False


class CMCClient:
    """Async client wrapper for the CoinMarketCap API with rate limiting and schema validation."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._rate_limiter = AsyncRateLimiter(
            max_calls=settings.CMC_RATE_LIMIT_PER_MINUTE,
            period_seconds=60.0,
        )
        self._cache = TTLCache(default_ttl_seconds=60.0, max_entries=500)

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazily initializes and returns the base httpx.AsyncClient instance."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.CMC_BASE_URL,
                headers={"Accept": "application/json"},
                timeout=settings.CMC_TIMEOUT_SECONDS,
            )
        return self._client

    async def close(self) -> None:
        """Closes the underlying HTTP client session."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _cache_key(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        normalized = dict(sorted((str(k), str(v)) for k, v in (params or {}).items() if v is not None))
        return f"{path}|{normalized}"

    def _handle_response(self, response: httpx.Response, response_model: Optional[Type[Any]] = None) -> Dict[str, Any]:
        """Validate the HTTP response and coerce it into the expected schema payload."""
        if not response.is_success:
            raise_for_status(response)

        payload = response.json()
        if response_model is None:
            return payload.get("data", {})

        validated = response_model.model_validate(payload)
        # Serialize the WHOLE validated response first (mode="python" recursively
        # converts every nested BaseModel -- including model instances sitting
        # inside a plain dict value, e.g. Dict[str, CryptoAssetData] -- into
        # plain dicts). Only then pull out "data". Previously this dumped just
        # the `.data` attribute, and skipped the dump entirely when `.data`
        # happened to be a plain dict/list container (as with CryptoQuotesResponse),
        # leaving nested model instances unconverted and invisible to `.get()`
        # calls downstream.
        dumped = validated.model_dump(mode="python")
        return dumped.get("data", dumped)

    async def _request_json(
        self,
        api_key: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        response_model: Optional[Type[Any]] = None,
        ttl_seconds: float = 30.0,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Perform a throttled request with optional TTL-based caching using the provided API key."""
        cache_key = self._cache_key(path, params) if use_cache else None
        if use_cache and cache_key is not None:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        headers = {
            "X-CMC_PRO_API_KEY": api_key,
            "Accept": "application/json",
        }

        for attempt in range(1, settings.CMC_MAX_RETRIES + 2):
            async with self._rate_limiter:
                try:
                    response = await self.client.get(path, params=params, headers=headers)
                    data = self._handle_response(response, response_model=response_model)
                    if use_cache and cache_key is not None:
                        await self._cache.set(cache_key, data, ttl_seconds=ttl_seconds)
                    return data
                except (CMCApiError, httpx.RequestError) as exc:
                    if not _is_retryable(exc) or attempt > settings.CMC_MAX_RETRIES:
                        raise
                    await asyncio.sleep(settings.CMC_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

        raise CMCApiError("CMC request failed after retries.", 500, 0)

    async def get_rwa_quotes(
        self,
        api_key: str,
        rwa_id: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches quotes and market data for Real-World Assets."""
        params: Dict[str, Any] = {}
        if rwa_id:
            params["rwa_id"] = rwa_id
        elif symbol:
            params["symbol"] = symbol

        return await self._request_json(
            api_key=api_key,
            path="/v5/real-world-assets/quotes/latest",
            params=params,
            response_model=RWAQuotesResponse,
            ttl_seconds=30.0,
            use_cache=True,
        )

    async def get_rwa_issuers_list(
        self,
        api_key: str,
        limit: int = 100,
        start: int = 1,
    ) -> Dict[str, Any]:
        """Fetches the list of registered RWA issuers."""
        params = {"limit": limit, "start": start}
        return await self._request_json(
            api_key=api_key,
            path="/v5/real-world-assets/issuers/list",
            params=params,
            response_model=RWAIssuersResponse,
            ttl_seconds=300.0,
            use_cache=True,
        )

    async def get_rwa_issuer(
        self,
        api_key: str,
        issuer_id: str,
        limit: int = 100,
        start: int = 1,
    ) -> Dict[str, Any]:
        """Fetches one RWA issuer and its token list."""
        params = {"issuer_id": issuer_id, "limit": limit, "start": start}
        return await self._request_json(
            api_key=api_key,
            path="/v5/real-world-assets/issuers",
            params=params,
            response_model=RWAIssuerResponse,
            ttl_seconds=300.0,
            use_cache=True,
        )

    async def get_crypto_quotes(self, api_key: str, symbol: str) -> Dict[str, Any]:
        """Fetches market quotes for standard cryptocurrencies (e.g., BTC, ETH)."""
        return await self._request_json(
            api_key=api_key,
            path="/v3/cryptocurrency/quotes/latest",
            params={"symbol": symbol},
            response_model=CryptoQuotesResponse,
            ttl_seconds=20.0,
            use_cache=True,
        )

    async def get_global_metrics(self, api_key: str) -> Dict[str, Any]:
        """Fetches global market cap and dominance indicators."""
        return await self._request_json(
            api_key=api_key,
            path="/v1/global-metrics/quotes/latest",
            params={},
            response_model=GlobalMetricsResponse,
            ttl_seconds=120.0,
            use_cache=True,
        )


# Singleton instance
cmc_client = CMCClient()