"""
Structured logging setup for the CMC RWA MCP server.

Design goals:
  - Human-readable console output on stderr (stdout is reserved for the MCP
    stdio transport, so logging to stdout would corrupt the protocol stream).
  - Never leak the CMC API key or full Authorization headers into logs.
  - A small helper for consistently logging outbound API calls (endpoint,
    params, status, latency, credits used) so every tool call leaves an
    auditable trail - useful for debugging rate limits and for the
    "evidence of a real API call" requirement in the hackathon submission.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

_CONFIGURED = False

# Matches CMC API keys (uuid-like) so they never end up in a log line even
# if a raw params/headers dict is passed straight to the logger.
_SECRET_PATTERN = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)

_SECRET_KEYS = {"x-cmc_pro_api_key", "cmc_api_key", "api_key", "authorization"}


def _redact(value: Any) -> Any:
    """Redacts anything that looks like an API key before it hits a log line."""
    if isinstance(value, str):
        return _SECRET_PATTERN.sub("****REDACTED****", value)
    if isinstance(value, dict):
        redacted: Dict[Any, Any] = {}
        for k, v in value.items():
            if str(k).lower() in _SECRET_KEYS:
                redacted[k] = "****REDACTED****"
            else:
                redacted[k] = _redact(v)
        return redacted
    return value


def configure_logging(level: int = logging.INFO) -> None:
    """Configures the root 'app' logger once. Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    logger = logging.getLogger("app")
    logger.setLevel(level)
    logger.propagate = False

    # IMPORTANT: log to stderr, never stdout - stdout carries the MCP
    # stdio JSON-RPC stream and any stray print/log line will break the client.
    handler = logging.StreamHandler(stream=sys.stderr)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    _CONFIGURED = True


def get_logger(name: str = "app") -> logging.Logger:
    """Returns a configured logger under the 'app' namespace."""
    configure_logging()
    return logging.getLogger(name)


@contextmanager
def log_api_call(
    logger: logging.Logger,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
) -> Iterator[Dict[str, Any]]:
    """
    Context manager that logs an outbound CMC API call with latency and outcome.

    Usage:
        with log_api_call(logger, "/v5/real-world-assets/quotes/latest", params) as ctx:
            response = await client.get(...)
            ctx["status_code"] = response.status_code
            ctx["credit_count"] = 1
    """
    start = time.monotonic()
    ctx: Dict[str, Any] = {"status_code": None, "credit_count": None, "error": None}
    safe_params = _redact(params or {})
    logger.info("CMC API request  | %s | params=%s", endpoint, safe_params)
    try:
        yield ctx
    except Exception as exc:  # noqa: BLE001 - log then re-raise
        ctx["error"] = str(exc)
        raise
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000
        if ctx.get("error"):
            logger.warning(
                "CMC API failed   | %s | %.1fms | error=%s",
                endpoint,
                elapsed_ms,
                _redact(ctx["error"]),
            )
        else:
            logger.info(
                "CMC API response | %s | %.1fms | status=%s | credits=%s",
                endpoint,
                elapsed_ms,
                ctx.get("status_code"),
                ctx.get("credit_count"),
            )
