from __future__ import annotations

from typing import Any, Dict, Optional


class CMCApiError(Exception):
    """Base exception for CoinMarketCap API errors."""

    def __init__(self, message: str, status_code: int = 500, error_code: int = 0, raw: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.raw = raw or {}
        super().__init__(f"CMC API Error [{status_code}] (Code {error_code}): {message}")

    @classmethod
    def from_response(cls, response: Any, fallback_message: Optional[str] = None) -> "CMCApiError":
        """Build a typed API error from an httpx response-like object or raw payload."""
        status_code = getattr(response, "status_code", 500)
        payload: Dict[str, Any] = {}

        try:
            payload = response.json() if hasattr(response, "json") else response or {}
        except Exception:
            payload = {}

        status = payload.get("status", {}) if isinstance(payload, dict) else {}
        error_message = status.get("error_message") or fallback_message or str(response)
        error_code = status.get("error_code", 0)
        return cls(error_message, status_code=status_code, error_code=error_code, raw=payload)

    @classmethod
    def from_status(cls, status_code: int, error_message: str, error_code: int = 0) -> "CMCApiError":
        """Create a typed API error directly from known response metadata."""
        return cls(error_message, status_code=status_code, error_code=error_code)


class CMCBadRequestError(CMCApiError):
    """Raised when query parameters or symbol lookup requests are malformed (HTTP 400)."""


class CMCUnauthorizedError(CMCApiError):
    """Raised when the X-CMC_PRO_API_KEY header is missing, invalid, or unauthorized (HTTP 401/403)."""


class CMCRateLimitError(CMCApiError):
    """Raised when client exceeds subscription tier API rate limits (HTTP 429)."""


class CMCNotFoundError(CMCApiError):
    """Raised when an RWA asset ID, symbol, or issuer lookup returns no results."""


def raise_for_status(response: Any, fallback_message: Optional[str] = None) -> None:
    """Translate an HTTP response to the correct CMC exception type."""
    if getattr(response, "is_success", True):
        return

    status_code = getattr(response, "status_code", 500)
    payload = {}
    try:
        payload = response.json() if hasattr(response, "json") else {}
    except Exception:
        payload = {}

    status = payload.get("status", {}) if isinstance(payload, dict) else {}
    error_message = status.get("error_message") or fallback_message or getattr(response, "text", "") or "CMC request failed."
    error_code = status.get("error_code", 0)

    if status_code == 400:
        raise CMCBadRequestError(error_message, status_code=status_code, error_code=error_code, raw=payload)
    if status_code in (401, 403):
        raise CMCUnauthorizedError(error_message, status_code=status_code, error_code=error_code, raw=payload)
    if status_code == 404:
        raise CMCNotFoundError(error_message, status_code=status_code, error_code=error_code, raw=payload)
    if status_code == 429:
        raise CMCRateLimitError(error_message, status_code=status_code, error_code=error_code, raw=payload)
    raise CMCApiError(error_message, status_code=status_code, error_code=error_code, raw=payload)