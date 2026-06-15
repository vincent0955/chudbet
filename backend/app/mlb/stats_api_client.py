"""Resilient, keyless MLB Stats API client (Requirements 6.1-6.4, 6.6).

This module is the **only** backend code that imports the ``statsapi`` library
(toddrob99/MLB-StatsAPI) or talks to the host ``statsapi.mlb.com`` (Requirement
2.2). Every other MLB component (ingestion, pricing) reaches the Stats API only
through :class:`MLBStatsAPIClient`.

Design (see design.md component 2):

- Typed public methods ``teams()``, ``roster()``, ``schedule()``, ``boxscore()``
  return parsed payloads and route through the private ``_call`` resilience layer.
- ``_call(fn, *, validate, description)``:
    * enforces the configured per-request timeout (Req 6.2);
    * on a transport/service error, a timeout, an empty body, or a payload missing
      the requested game/player fields (``validate`` returns ``False``), retries up
      to ``max_attempts`` with a strictly increasing delay ``backoff_base * 2**attempt``
      between attempts (Req 6.3);
    * on exhaustion, logs a diagnostic identifying the failed request and raises
      :class:`MLBStatsAPIError` -- it never returns partial or fabricated data
      (Req 6.4);
    * spaces consecutive requests by at least ``min_interval_sec`` (Req 6.6).
- No API key or credential is configured or sent (Req 6.1): the underlying
  ``statsapi`` wrapper is keyless.

The ``statsapi`` import is performed lazily inside the transport so the module
imports cleanly even where the optional dependency is not installed; it remains
the sole site of that import.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date
from typing import Any, Callable, TypeVar

from app.mlb.config import MLBClientConfig, get_client_config

logger = logging.getLogger(__name__)

__all__ = [
    "MLBStatsAPIError",
    "MLBClientConfig",
    "MLBStatsAPIClient",
    "StatsapiTransport",
    "TeamPayload",
    "RosterEntry",
    "SchedulePayload",
    "BoxScorePayload",
]

# Permissive JSON payload aliases. The Stats API returns loosely-typed dicts; the
# ingestion service is responsible for extracting the specific fields it needs.
TeamPayload = dict[str, Any]
RosterEntry = dict[str, Any]
SchedulePayload = dict[str, Any]
BoxScorePayload = dict[str, Any]

T = TypeVar("T")

# MLB's ``sportId`` in the Stats API (1 == Major League Baseball).
MLB_SPORT_ID = 1


class MLBStatsAPIError(RuntimeError):
    """Failure signal raised after retries are exhausted (Req 6.4).

    Returned to the caller in place of partial or fabricated data. The MLB
    ingestion service catches this per game so one failure does not abort a batch
    (Req 6.5, handled in the ingestion layer).
    """

    def __init__(self, description: str, attempts: int) -> None:
        self.description = description
        self.attempts = attempts
        super().__init__(
            f"MLB Stats API request failed after {attempts} attempt(s): {description}"
        )


class _RequestTimeout(Exception):
    """Internal, retryable signal that a request exceeded the per-request timeout."""


class _NoUsableData(Exception):
    """Internal, retryable signal that a response carried no usable data."""


# --- "usable data" validators (Req 6.3) -------------------------------------
#
# Each validator decides whether a raw transport response is usable. A ``False``
# result is treated exactly like a transport error: the request is retried, and
# on exhaustion the client signals failure rather than returning the payload.


def _validate_teams(result: Any) -> bool:
    """Usable when the payload carries a non-empty ``teams`` list (MLB always has teams)."""
    return (
        isinstance(result, dict)
        and isinstance(result.get("teams"), list)
        and len(result["teams"]) > 0
    )


def _validate_roster(result: Any) -> bool:
    """Usable when the payload carries a ``roster`` list.

    An empty roster is *usable* data: the Stats API legitimately reports a team
    with no current roster entries, which the ingestion service handles with a
    diagnostic (Req 3.5). Only a missing ``roster`` field is treated as no usable
    data.
    """
    return isinstance(result, dict) and isinstance(result.get("roster"), list)


def _validate_schedule(result: Any) -> bool:
    """Usable when the payload is a list.

    ``statsapi.schedule`` returns a list of game dicts; an empty list is a valid
    "no games scheduled in this window" result, not a failure.
    """
    return isinstance(result, list)


def _validate_boxscore(result: Any) -> bool:
    """Usable when the payload carries the requested ``home``/``away`` game fields."""
    return (
        isinstance(result, dict)
        and isinstance(result.get("home"), dict)
        and isinstance(result.get("away"), dict)
    )


class StatsapiTransport:
    """Thin wrapper around the keyless ``statsapi`` library.

    This is the single site of the ``statsapi`` import / ``statsapi.mlb.com``
    access (Req 2.2). The import is lazy so importing this module never requires
    the optional dependency to be installed.
    """

    @staticmethod
    def _statsapi():  # pragma: no cover - thin import shim
        import statsapi  # keyless wrapper over statsapi.mlb.com (Req 6.1)

        return statsapi

    def teams(self) -> dict:
        return self._statsapi().get("teams", {"sportId": MLB_SPORT_ID})

    def roster(self, mlb_team_id: int) -> dict:
        return self._statsapi().get("team_roster", {"teamId": int(mlb_team_id)})

    def schedule(self, start: date, end: date) -> list:
        return self._statsapi().schedule(
            start_date=start.strftime("%m/%d/%Y"),
            end_date=end.strftime("%m/%d/%Y"),
            sportId=MLB_SPORT_ID,
        )

    def boxscore(self, mlb_game_id: int) -> dict:
        return self._statsapi().boxscore_data(int(mlb_game_id))


class MLBStatsAPIClient:
    """Keyless, retrying client for the MLB Stats API.

    The transport, clock, and sleep function are injectable so the resilience
    behavior can be exercised deterministically without the network.
    """

    def __init__(
        self,
        config: MLBClientConfig | None = None,
        *,
        transport: StatsapiTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config or get_client_config()
        self._transport = transport or StatsapiTransport()
        self._sleep = sleep
        self._monotonic = monotonic
        # Monotonic timestamp of the most recently issued request (any attempt),
        # used to space consecutive requests by at least ``min_interval_sec``.
        self._last_request_at: float | None = None

    # --- public, typed API -------------------------------------------------

    def teams(self) -> list[TeamPayload]:
        """Return current MLB teams. Raises :class:`MLBStatsAPIError` on failure."""
        raw = self._call(
            self._transport.teams, validate=_validate_teams, description="teams"
        )
        return list(raw["teams"])

    def roster(self, mlb_team_id: int) -> list[RosterEntry]:
        """Return a team's roster entries (possibly empty). Raises on failure."""
        raw = self._call(
            lambda: self._transport.roster(mlb_team_id),
            validate=_validate_roster,
            description=f"roster(team_id={mlb_team_id})",
        )
        return list(raw["roster"])

    def schedule(self, start: date, end: date) -> list[SchedulePayload]:
        """Return scheduled games in ``[start, end]`` (possibly empty). Raises on failure."""
        raw = self._call(
            lambda: self._transport.schedule(start, end),
            validate=_validate_schedule,
            description=f"schedule(start={start.isoformat()}, end={end.isoformat()})",
        )
        return list(raw)

    def boxscore(self, mlb_game_id: int) -> BoxScorePayload:
        """Return a game's box-score payload. Raises on failure."""
        return self._call(
            lambda: self._transport.boxscore(mlb_game_id),
            validate=_validate_boxscore,
            description=f"boxscore(game_id={mlb_game_id})",
        )

    # --- resilience core ---------------------------------------------------

    def _call(
        self,
        fn: Callable[[], T],
        *,
        validate: Callable[[Any], bool],
        description: str,
    ) -> T:
        """Issue ``fn`` with timeout, retry, spacing, and a final failure signal.

        See the module docstring for the full contract (Req 6.2, 6.3, 6.4, 6.6).
        """
        attempts = self._config.max_attempts
        last_error: Exception | None = None

        for attempt in range(attempts):
            # Space this request at least ``min_interval_sec`` from the previous
            # one (Req 6.6). Applies to every issued request, including retries.
            self._respect_min_interval()

            try:
                result = self._invoke_with_timeout(fn)
            except Exception as exc:  # transport/service error or timeout (Req 6.3)
                self._last_request_at = self._monotonic()
                last_error = exc
                logger.warning(
                    "MLB Stats API request %s failed on attempt %d/%d: %s",
                    description,
                    attempt + 1,
                    attempts,
                    exc,
                )
            else:
                self._last_request_at = self._monotonic()
                if validate(result):
                    return result
                # 200-but-empty / missing-fields is a retryable no-usable-data
                # condition (Req 6.3), never returned to the caller.
                last_error = _NoUsableData(description)
                logger.warning(
                    "MLB Stats API request %s returned no usable data on attempt %d/%d",
                    description,
                    attempt + 1,
                    attempts,
                )

            # Back off before the next attempt with a strictly increasing delay
            # ``backoff_base * 2**attempt`` (Req 6.3); never after the last attempt.
            if attempt < attempts - 1:
                delay = self._config.backoff_base_sec * (2 ** attempt)
                if delay > 0:
                    self._sleep(delay)

        # Retries exhausted: log a diagnostic and signal failure (Req 6.4).
        logger.error(
            "MLB Stats API request %s exhausted %d attempt(s); signaling failure",
            description,
            attempts,
        )
        raise MLBStatsAPIError(description, attempts) from last_error

    def _respect_min_interval(self) -> None:
        """Sleep so consecutive issued requests are spaced by ``min_interval_sec`` (Req 6.6)."""
        if self._last_request_at is None:
            return
        min_interval = self._config.min_interval_sec
        if min_interval <= 0:
            return
        elapsed = self._monotonic() - self._last_request_at
        remaining = min_interval - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _invoke_with_timeout(self, fn: Callable[[], T]) -> T:
        """Run ``fn`` enforcing the per-request timeout (Req 6.2).

        The call runs on a daemon worker thread so a hung request cannot block the
        caller past the timeout (the underlying ``statsapi``/``requests`` call is
        not cancellable, so the abandoned daemon thread is left to exit with the
        process). A timeout is surfaced as the retryable :class:`_RequestTimeout`.
        """
        timeout = self._config.timeout_sec
        box: dict[str, Any] = {}

        def runner() -> None:
            try:
                box["result"] = fn()
            except BaseException as exc:  # noqa: BLE001 - propagated to caller below
                box["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(timeout)

        if thread.is_alive():
            raise _RequestTimeout(f"request exceeded {timeout:g}s timeout")
        if "error" in box:
            raise box["error"]
        return box["result"]
