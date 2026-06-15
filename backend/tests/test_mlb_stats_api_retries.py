"""Property-based and example tests for MLB Stats API client retry resilience.

Exercises the private resilience core of :class:`app.mlb.stats_api_client.MLBStatsAPIClient`
through its public ``teams()`` method: a request that keeps failing (transport
error or no-usable-data) is retried a *bounded* number of times with a *strictly
increasing* delay between attempts, and on exhaustion the client signals failure
by raising :class:`~app.mlb.stats_api_client.MLBStatsAPIError` rather than
returning partial or fabricated data.

The transport is mocked and the clock/``sleep`` are spies, so the retry/backoff
behavior is exercised deterministically without any network access.

Feature: mlb-support, Property 9
Validates: Requirements 6.3, 6.4
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.mlb.config import MLBClientConfig
from app.mlb.stats_api_client import MLBStatsAPIClient, MLBStatsAPIError


# --- Test doubles -----------------------------------------------------------


class _SleepSpy:
    """Records every delay passed to ``sleep`` instead of actually sleeping."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class _FailingTransport:
    """Mock transport whose ``teams`` always fails, counting invocations.

    Two failure modes are exercised:

    - ``mode="error"``: raises a transport/service error on every call
      (the retryable error path of Req 6.3).
    - ``mode="no_usable_data"``: returns a 200-but-empty payload that fails the
      ``teams`` validator (the retryable no-usable-data path of Req 6.3).
    """

    def __init__(self, mode: str) -> None:
        self._mode = mode
        self.calls = 0

    def teams(self) -> dict:
        self.calls += 1
        if self._mode == "error":
            raise ConnectionError("simulated transport failure")
        # no_usable_data: missing/empty "teams" -> fails _validate_teams.
        return {"teams": []}


def _make_client(
    *,
    max_attempts: int,
    backoff_base_sec: float,
    transport: _FailingTransport,
    sleep: _SleepSpy,
) -> MLBStatsAPIClient:
    """Build a client with deterministic, network-free dependencies.

    ``min_interval_sec`` is 0 so the only ``sleep`` calls are the inter-attempt
    backoff delays, and ``monotonic`` is a fixed clock (spacing is disabled).
    """
    config = MLBClientConfig(
        timeout_sec=10.0,
        max_attempts=max_attempts,
        min_interval_sec=0.0,
        backoff_base_sec=backoff_base_sec,
    )
    return MLBStatsAPIClient(
        config,
        transport=transport,
        sleep=sleep,
        monotonic=lambda: 0.0,
    )


# --- Property 9 (Req 6.3, 6.4) ----------------------------------------------


@settings(deadline=None, max_examples=200)
@given(
    max_attempts=st.integers(min_value=1, max_value=10),
    backoff_base_sec=st.floats(
        min_value=0.001, max_value=5.0, allow_nan=False, allow_infinity=False
    ),
    mode=st.sampled_from(["error", "no_usable_data"]),
)
def test_property9_bounded_increasing_retries_then_failure(
    max_attempts: int, backoff_base_sec: float, mode: str
) -> None:
    """**Validates: Requirements 6.3, 6.4**

    Feature: mlb-support, Property 9

    For any configured ``max_attempts`` (1..10) and positive backoff base, a
    persistently failing request:

    - is retried a *bounded* number of times: the transport is invoked exactly
      ``max_attempts`` times, never more (Req 6.3);
    - waits a *strictly increasing* delay between attempts equal to
      ``backoff_base * 2**attempt`` for attempts ``0..max_attempts-2``, and never
      sleeps after the final attempt (Req 6.3);
    - then *signals failure* by raising ``MLBStatsAPIError`` carrying the attempt
      count, rather than returning partial or fabricated data (Req 6.4).
    """
    transport = _FailingTransport(mode)
    sleep = _SleepSpy()
    client = _make_client(
        max_attempts=max_attempts,
        backoff_base_sec=backoff_base_sec,
        transport=transport,
        sleep=sleep,
    )

    with pytest.raises(MLBStatsAPIError) as exc_info:
        client.teams()

    # Failure signal carries the bounded attempt count (Req 6.4).
    assert exc_info.value.attempts == max_attempts

    # Bounded retries: the transport was invoked exactly max_attempts times.
    assert transport.calls == max_attempts

    # One backoff delay sits between each pair of attempts, none after the last.
    expected_delays = [
        backoff_base_sec * (2 ** attempt) for attempt in range(max_attempts - 1)
    ]
    assert sleep.delays == expected_delays

    # Delays are strictly increasing (each step doubles a positive base).
    assert all(
        earlier < later
        for earlier, later in zip(sleep.delays, sleep.delays[1:])
    )


@settings(deadline=None, max_examples=200)
@given(
    backoff_base_sec=st.floats(
        min_value=0.001, max_value=5.0, allow_nan=False, allow_infinity=False
    ),
    mode=st.sampled_from(["error", "no_usable_data"]),
)
def test_property9_zero_attempts_signals_failure_without_calling(
    backoff_base_sec: float, mode: str
) -> None:
    """**Validates: Requirements 6.3, 6.4**

    Feature: mlb-support, Property 9

    With ``max_attempts == 0`` (the lower bound of the allowed range), the client
    issues no request at all (bounded by 0) and immediately signals failure with
    ``MLBStatsAPIError`` reporting 0 attempts -- never fabricating a result.
    """
    transport = _FailingTransport(mode)
    sleep = _SleepSpy()
    client = _make_client(
        max_attempts=0,
        backoff_base_sec=backoff_base_sec,
        transport=transport,
        sleep=sleep,
    )

    with pytest.raises(MLBStatsAPIError) as exc_info:
        client.teams()

    assert exc_info.value.attempts == 0
    assert transport.calls == 0
    assert sleep.delays == []


# --- Example anchors --------------------------------------------------------


class TestRetryExamples:
    """Concrete edge cases for the bounded/increasing retry contract."""

    def test_single_attempt_no_backoff_then_failure(self) -> None:
        """max_attempts=1: one call, no backoff sleep, failure signaled."""
        transport = _FailingTransport("error")
        sleep = _SleepSpy()
        client = _make_client(
            max_attempts=1,
            backoff_base_sec=0.5,
            transport=transport,
            sleep=sleep,
        )

        with pytest.raises(MLBStatsAPIError):
            client.teams()

        assert transport.calls == 1
        assert sleep.delays == []

    def test_three_attempts_doubling_delays(self) -> None:
        """max_attempts=3, base=0.5: delays are [0.5, 1.0] (strictly increasing)."""
        transport = _FailingTransport("error")
        sleep = _SleepSpy()
        client = _make_client(
            max_attempts=3,
            backoff_base_sec=0.5,
            transport=transport,
            sleep=sleep,
        )

        with pytest.raises(MLBStatsAPIError):
            client.teams()

        assert transport.calls == 3
        assert sleep.delays == [0.5, 1.0]

    def test_no_usable_data_is_retried_like_an_error(self) -> None:
        """A 200-but-empty payload is retried and never returned to the caller."""
        transport = _FailingTransport("no_usable_data")
        sleep = _SleepSpy()
        client = _make_client(
            max_attempts=4,
            backoff_base_sec=0.25,
            transport=transport,
            sleep=sleep,
        )

        with pytest.raises(MLBStatsAPIError):
            client.teams()

        assert transport.calls == 4
        assert sleep.delays == [0.25, 0.5, 1.0]

    def test_zero_backoff_base_makes_no_sleep_calls(self) -> None:
        """With base 0, the client skips sleeping yet still retries to the bound."""
        transport = _FailingTransport("error")
        sleep = _SleepSpy()
        client = _make_client(
            max_attempts=5,
            backoff_base_sec=0.0,
            transport=transport,
            sleep=sleep,
        )

        with pytest.raises(MLBStatsAPIError):
            client.teams()

        assert transport.calls == 5
        # delay == 0 short-circuits the sleep call entirely (no zero-delays).
        assert sleep.delays == []
