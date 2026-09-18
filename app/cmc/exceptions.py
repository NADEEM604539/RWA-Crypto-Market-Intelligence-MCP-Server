from typing import Optional


class CMCApiError(Exception):
    """Base exception for CoinMarketCap API errors."""
    def __init__(self, message: str, status_code: int = 500, error_code: int = 0):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(f"CMC API Error [{status_code}] (Code {error_code}): {message}")


class CMCBadRequestError(CMCApiError):
    """Raised when query parameters or symbol lookup requests are malformed (HTTP 400)."""
    pass


class CMCUnauthorizedError(CMCApiError):
    """Raised when the X-CMC_PRO_API_KEY header is missing, invalid, or unauthorized (HTTP 401/403)."""
    pass


class CMCRateLimitError(CMCApiError):
    """Raised when client exceeds subscription tier API rate limits (HTTP 429)."""
    pass


class CMCNotFoundError(CMCApiError):
    """Raised when an RWA asset ID, symbol, or issuer lookup returns no results."""
    pass