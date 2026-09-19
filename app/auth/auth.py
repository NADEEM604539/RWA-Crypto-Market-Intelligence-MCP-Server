import asyncio
from collections import defaultdict
import json
import time

import httpx

# ============================================================================
# 1. Rate Limiter (In-Memory Sliding Window)
# ============================================================================
class RateLimiter:
    """Per-API key sliding window rate limiter."""

    def __init__(self, requests_per_minute: int = 30):
        self.rpm = requests_per_minute
        self.requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, api_key: str) -> tuple[bool, int]:
        async with self._lock:
            now = time.time()
            cutoff = now - 60.0
            # Clean up records older than 60 seconds
            self.requests[api_key] = [t for t in self.requests[api_key] if t > cutoff]
            if len(self.requests[api_key]) >= self.rpm:
                retry_after = int(60 - (now - self.requests[api_key][0]))
                return False, max(1, retry_after)
            self.requests[api_key].append(now)
            return True, 0


rate_limiter = RateLimiter(requests_per_minute=30)

# ============================================================================
# 2. API Key Verification & Cache
# ============================================================================
VALIDATED_KEYS_CACHE: dict[str, float] = {}  # key -> timestamp of validation
CACHE_TTL_SECONDS = 300.0  # 5 minutes cache to prevent hammering /v1/key/info


async def verify_cmc_api_key(api_key: str) -> tuple[bool, str]:
    """Validates the API key against CoinMarketCap's key info endpoint."""
    now = time.time()
    # Check cache first
    if api_key in VALIDATED_KEYS_CACHE and (now - VALIDATED_KEYS_CACHE[api_key]) < CACHE_TTL_SECONDS:
        return True, "Key verified (cached)"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://pro-api.coinmarketcap.com/v1/key/info",
                headers={"X-CMC_PRO_API_KEY": api_key, "Accept": "application/json"},
            )
            if response.status_code == 200:
                VALIDATED_KEYS_CACHE[api_key] = now
                return True, "Key valid"
            elif response.status_code in (401, 403):
                return False, "Invalid or unauthorized CoinMarketCap API Key"
            else:
                return False, f"CMC API returned error status {response.status_code}"
    except Exception as err:
        return False, f"Failed to reach CoinMarketCap API: {str(err)}"


async def authenticate_and_rate_limit(headers: dict) -> tuple[str | None, str | None]:
    """
    Pipeline to extract key, check rate limits, and verify key authenticity.
    Returns (api_key, error_json_payload).
    """
    # 1. Extract Header Key
    api_key = (
        headers.get("x-cmc_pro_api_key")
        or headers.get("authorization", "").replace("Bearer ", "").strip()
    )

    if not api_key:
        error_payload = json.dumps({
            "status": "error",
            "error": "Unauthorized",
            "message": "Missing CoinMarketCap API Key. Include 'X-CMC_PRO_API_KEY' in your HTTP headers."
        }, indent=2)
        return None, error_payload

    # 2. Check Rate Limits
    allowed, retry_after = await rate_limiter.is_allowed(api_key)
    if not allowed:
        error_payload = json.dumps({
            "status": "error",
            "error": "Too Many Requests",
            "message": f"Rate limit exceeded (30 req/min). Try again in {retry_after} seconds.",
            "retry_after": retry_after
        }, indent=2)
        return None, error_payload

    # 3. Verify Key Validity
    is_valid, reason = await verify_cmc_api_key(api_key)
    if not is_valid:
        error_payload = json.dumps({
            "status": "error",
            "error": "Unauthorized",
            "message": f"API key verification failed: {reason}"
        }, indent=2)
        return None, error_payload

    return api_key, None