from typing import Any, Dict, Optional
import httpx

from app.config import settings
from app.cmc.exceptions import (
    CMCApiError,
    CMCBadRequestError,
    CMCNotFoundError,
    CMCRateLimitError,
    CMCUnauthorizedError,
)


class CMCClient:
    """Async client wrapper for the CoinMarketCap API."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazily initializes and returns the httpx.AsyncClient instance."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.CMC_BASE_URL,
                headers={
                    "X-CMC_PRO_API_KEY": settings.CMC_API_KEY,
                    "Accept": "application/json",
                },
                timeout=settings.CMC_TIMEOUT_SECONDS,
            )
        return self._client

    async def close(self) -> None:
        """Closes the underlying HTTP client session."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        """
        Parses response payload and raises domain-specific exceptions on error status codes.
        """
        if response.is_success:
            payload = response.json()
            return payload.get("data", {})

        status_code = response.status_code
        try:
            error_payload = response.json().get("status", {})
            error_msg = error_payload.get("error_message") or response.text
            error_code = error_payload.get("error_code", 0)
        except Exception:
            error_msg = response.text
            error_code = 0

        if status_code == 400:
            raise CMCBadRequestError(error_msg, status_code, error_code)
        elif status_code in (401, 403):
            raise CMCUnauthorizedError(error_msg, status_code, error_code)
        elif status_code == 404:
            raise CMCNotFoundError(error_msg, status_code, error_code)
        elif status_code == 429:
            raise CMCRateLimitError(error_msg, status_code, error_code)
        else:
            raise CMCApiError(error_msg, status_code, error_code)

    async def get_rwa_quotes(
        self, 
        rwa_id: Optional[str] = None, 
        symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fetches quotes and market data for Real-World Assets.
        """
        params: Dict[str, Any] = {}
        if rwa_id:
            params["rwa_id"] = rwa_id
        elif symbol:
            params["symbol"] = symbol

        response = await self.client.get(
            "/v5/real-world-assets/quotes/latest", 
            params=params
        )
        return self._handle_response(response)

    async def get_rwa_issuers_list(self, limit: int = 100, start: int = 1) -> Dict[str, Any]:
        """
        Fetches the list of registered RWA issuers.
        """
        params = {"limit": limit, "start": start}
        response = await self.client.get(
            "/v5/real-world-assets/issuers/list", 
            params=params
        )
        return self._handle_response(response)

    async def get_rwa_issuer(self, issuer_id: str, limit: int = 100, start: int = 1) -> Dict[str, Any]:
        """
        Fetches one RWA issuer and its token list.
        """
        params = {"issuer_id": issuer_id, "limit": limit, "start": start}
        response = await self.client.get(
            "/v5/real-world-assets/issuers",
            params=params,
        )
        return self._handle_response(response)

    async def get_crypto_quotes(self, symbol: str) -> Dict[str, Any]:
        """
        Fetches market quotes for standard cryptocurrencies (e.g., BTC, ETH).
        """
        params = {"symbol": symbol}
        response = await self.client.get(
            "/v3/cryptocurrency/quotes/latest", 
            params=params
        )
        return self._handle_response(response)

    async def get_global_metrics(self) -> Dict[str, Any]:
        """
        Fetches global market cap and dominance indicators.
        """
        response = await self.client.get("/v1/global-metrics/quotes/latest")
        return self._handle_response(response)


# Singleton instance
cmc_client = CMCClient()