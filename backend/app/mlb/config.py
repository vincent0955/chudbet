"""MLB configuration getters (Requirements 6.2, 6.3, 6.6).

All MLB-specific environment identifiers are read here, NOT in shared
``app/core/config.py``, so no MLB-specific identifiers leak into shared modules
(Requirement 2.4).

Only the Stats API client knobs are clamped here, per the spec:

- ``MLB_API_TIMEOUT_SEC``      default 10, clamped to [1, 60]   (Req 6.2)
- ``MLB_API_MAX_ATTEMPTS``     default 3,  clamped to [0, 10]   (Req 6.3)
- ``MLB_API_MIN_INTERVAL_SEC`` default 1,  floored at 0         (Req 6.6)

``MLB_API_BACKOFF_BASE_SEC`` provides the increasing inter-attempt delay
(``backoff_base * 2**attempt``) consumed by the client in task 3.1.

The remaining getters (lookbacks, sample sizes, schedule window) expose sensible
baseball defaults and fall back to those defaults on missing/invalid input. The
worker ingest interval is exposed as the *raw* string so the worker (task 6.2)
can perform its own negative/non-numeric/``> 86400`` validation.

These getters are intentionally uncached so clamping is evaluated against the
current environment on every call (which keeps the clamp behavior easy to test).
"""

import os
from dataclasses import dataclass
from typing import Literal

# --- Stats API client defaults / clamp bounds (Req 6.2, 6.3, 6.6) ---
API_TIMEOUT_DEFAULT_SEC = 10.0
API_TIMEOUT_MIN_SEC = 1.0
API_TIMEOUT_MAX_SEC = 60.0

API_MAX_ATTEMPTS_DEFAULT = 3
API_MAX_ATTEMPTS_MIN = 0
API_MAX_ATTEMPTS_MAX = 10

API_MIN_INTERVAL_DEFAULT_SEC = 1.0
API_MIN_INTERVAL_FLOOR_SEC = 0.0

API_BACKOFF_BASE_DEFAULT_SEC = 0.5
API_BACKOFF_BASE_FLOOR_SEC = 0.0

# --- Pricing / ingestion defaults (sensible baseball baselines) ---
GAME_LOOKBACK_DEFAULT = 10          # prior MLB games used for game-market projections
PROP_LOOKBACK_DAYS_DEFAULT = 30     # rolling window (days) for player-prop averages
PROP_MIN_SAMPLES_DEFAULT = 5        # min prior games before a prop line is offered
GAME_MIN_SAMPLES_DEFAULT = 3        # min prior games before defaults kick in for markets
SCHEDULE_MAX_DAYS_DEFAULT = 7       # max schedule ingestion window in days

# --- Worker defaults ---
WORKER_INGEST_INTERVAL_DEFAULT_RAW = "300"  # raw string; worker validates (task 6.2)
WORKER_SETTLE_INTERVAL_DEFAULT_SEC = 300


def _get_float(name: str, default: float) -> float:
    """Read ``name`` as a float, falling back to ``default`` when unset/invalid."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    """Read ``name`` as an int, falling back to ``default`` when unset/invalid."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into the inclusive ``[low, high]`` range."""
    return max(low, min(high, value))


# --- Stats API client config (Req 6.2, 6.3, 6.6) ---


def get_api_timeout_sec() -> float:
    """Per-request timeout, default 10, clamped to [1, 60] (Req 6.2)."""
    value = _get_float("MLB_API_TIMEOUT_SEC", API_TIMEOUT_DEFAULT_SEC)
    return _clamp(value, API_TIMEOUT_MIN_SEC, API_TIMEOUT_MAX_SEC)


def get_api_max_attempts() -> int:
    """Max retry attempts, default 3, clamped to [0, 10] (Req 6.3)."""
    value = _get_int("MLB_API_MAX_ATTEMPTS", API_MAX_ATTEMPTS_DEFAULT)
    return int(_clamp(value, API_MAX_ATTEMPTS_MIN, API_MAX_ATTEMPTS_MAX))


def get_api_min_interval_sec() -> float:
    """Minimum spacing between consecutive requests, default 1, floored at 0 (Req 6.6)."""
    value = _get_float("MLB_API_MIN_INTERVAL_SEC", API_MIN_INTERVAL_DEFAULT_SEC)
    return max(API_MIN_INTERVAL_FLOOR_SEC, value)


def get_api_backoff_base_sec() -> float:
    """Base delay for the increasing inter-attempt backoff (``base * 2**attempt``).

    Floored at 0 so a configured negative value never yields a decreasing delay.
    """
    value = _get_float("MLB_API_BACKOFF_BASE_SEC", API_BACKOFF_BASE_DEFAULT_SEC)
    return max(API_BACKOFF_BASE_FLOOR_SEC, value)


@dataclass(frozen=True)
class MLBClientConfig:
    """Resilience configuration for the MLB Stats API client (consumed in task 3.1)."""

    timeout_sec: float
    max_attempts: int
    min_interval_sec: float
    backoff_base_sec: float


def get_client_config() -> MLBClientConfig:
    """Build the clamped Stats API client config from the environment."""
    return MLBClientConfig(
        timeout_sec=get_api_timeout_sec(),
        max_attempts=get_api_max_attempts(),
        min_interval_sec=get_api_min_interval_sec(),
        backoff_base_sec=get_api_backoff_base_sec(),
    )


# --- Pricing / ingestion getters ---


def get_game_lookback() -> int:
    """Number of prior MLB games used for game-market projections (Req 8.4)."""
    return _get_int("MLB_GAME_LOOKBACK", GAME_LOOKBACK_DEFAULT)


def get_prop_lookback_days() -> int:
    """Rolling window in days for player-prop averages (Req 9.2)."""
    return _get_int("MLB_PROP_LOOKBACK_DAYS", PROP_LOOKBACK_DAYS_DEFAULT)


def get_prop_min_samples() -> int:
    """Minimum prior games before a prop line is offered (Req 9.3)."""
    return _get_int("MLB_PROP_MIN_SAMPLES", PROP_MIN_SAMPLES_DEFAULT)


def get_game_min_samples() -> int:
    """Minimum prior games before baseball defaults are used for markets (Req 8.6)."""
    return _get_int("MLB_GAME_MIN_SAMPLES", GAME_MIN_SAMPLES_DEFAULT)


def get_schedule_max_days() -> int:
    """Maximum schedule ingestion window in days (Req 4.1)."""
    return _get_int("MLB_SCHEDULE_MAX_DAYS", SCHEDULE_MAX_DAYS_DEFAULT)


# --- Worker getters ---


def get_worker_ingest_interval_raw() -> str:
    """Raw ``MLB_WORKER_INGEST_INTERVAL_SEC`` value.

    Returned unparsed so the MLB worker (task 6.2) can classify negative,
    non-numeric, and ``> 86400`` values itself (Req 7.2, 7.3, 7.4).
    """
    raw = os.getenv("MLB_WORKER_INGEST_INTERVAL_SEC", "").strip()
    return raw if raw else WORKER_INGEST_INTERVAL_DEFAULT_RAW


def get_worker_settle_interval_sec() -> int:
    """Settlement job interval in seconds (falls back to default on invalid input)."""
    return _get_int("MLB_WORKER_SETTLE_INTERVAL_SEC", WORKER_SETTLE_INTERVAL_DEFAULT_SEC)


WorkerIngestIntervalMode = Literal["schedule", "idle", "invalid"]


@dataclass(frozen=True)
class WorkerIngestIntervalClassification:
    """Classification of ``MLB_WORKER_INGEST_INTERVAL_SEC`` (Req 7.2–7.4).

    - ``schedule``: positive value in ``[1, 86400]`` — run ingest on that interval.
    - ``idle``: ``0`` — keep the worker alive but never schedule ingest.
    - ``invalid``: negative, non-numeric, or ``> 86400`` — log and exit the process.
    """

    mode: WorkerIngestIntervalMode
    seconds: int | None = None


def classify_worker_ingest_interval(raw: str) -> WorkerIngestIntervalClassification:
    """Classify the raw ingest-interval env value (Req 7.2, 7.3, 7.4)."""
    stripped = raw.strip()
    if not stripped:
        return WorkerIngestIntervalClassification(mode="invalid")

    try:
        value = int(stripped)
    except ValueError:
        return WorkerIngestIntervalClassification(mode="invalid")

    if value < 0 or value > 86400:
        return WorkerIngestIntervalClassification(mode="invalid")
    if value == 0:
        return WorkerIngestIntervalClassification(mode="idle")
    return WorkerIngestIntervalClassification(mode="schedule", seconds=value)
