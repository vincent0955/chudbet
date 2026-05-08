"""Tune nba_api HTTP behavior for slow paths (e.g. AWS egress to stats.nba.com).

nba_api passes timeout=30 to requests by default; datacenter IPs often need longer reads.
Set env vars before any stats endpoints are called:

  CHUDBET_NBA_HTTP_CONNECT_TIMEOUT — connect timeout seconds (default 15)
  CHUDBET_NBA_HTTP_READ_TIMEOUT   — read timeout seconds (default 120)
  CHUDBET_NBA_HTTP_RETRIES        — retries after read/connect timeout (default 3)
  CHUDBET_NBA_HTTP_RETRY_BACKOFF_SEC — base backoff before retry (default 2)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_PATCH_APPLIED = False


def _float_env(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _is_retryable(exc: BaseException) -> bool:
    try:
        import requests

        return isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))
    except Exception:
        return False


def apply_nba_http_patches() -> None:
    """Monkey-patch nba_api NBAHTTP.send_api_request once (idempotent)."""
    global _PATCH_APPLIED
    if _PATCH_APPLIED:
        return

    from nba_api.library import http as nba_http

    connect = _float_env("CHUDBET_NBA_HTTP_CONNECT_TIMEOUT", 15.0)
    read = _float_env("CHUDBET_NBA_HTTP_READ_TIMEOUT", 120.0)
    retries = _int_env("CHUDBET_NBA_HTTP_RETRIES", 3)
    backoff = _float_env("CHUDBET_NBA_HTTP_RETRY_BACKOFF_SEC", 2.0)

    orig = nba_http.NBAHTTP.send_api_request

    def send_api_request(
        self: Any,
        endpoint: Any,
        parameters: Any,
        referer: Any = None,
        proxy: Any = None,
        headers: Any = None,
        timeout: Any = None,
        raise_exception_on_error: bool = False,
    ) -> Any:
        # Prefer generous (connect, read); bump read vs endpoint default (often 30).
        if timeout is None:
            eff_timeout: tuple[float, float] | float = (connect, read)
        elif isinstance(timeout, (int, float)):
            eff_timeout = (connect, max(read, float(timeout)))
        elif isinstance(timeout, tuple) and len(timeout) == 2:
            eff_timeout = (float(timeout[0]), max(read, float(timeout[1])))
        else:
            eff_timeout = timeout

        last_exc: BaseException | None = None
        for attempt in range(retries + 1):
            try:
                return orig(
                    self,
                    endpoint,
                    parameters,
                    referer=referer,
                    proxy=proxy,
                    headers=headers,
                    timeout=eff_timeout,
                    raise_exception_on_error=raise_exception_on_error,
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= retries or not _is_retryable(exc):
                    raise
                sleep_s = backoff * (2**attempt)
                logger.warning(
                    "NBA HTTP attempt %s/%s failed (%s); retrying in %.1fs",
                    attempt + 1,
                    retries + 1,
                    exc,
                    sleep_s,
                )
                time.sleep(sleep_s)
        assert last_exc is not None
        raise last_exc

    nba_http.NBAHTTP.send_api_request = send_api_request  # type: ignore[method-assign]
    _PATCH_APPLIED = True
    logger.debug(
        "nba_api HTTP patched: connect=%ss read=%ss retries=%s",
        connect,
        read,
        retries,
    )
