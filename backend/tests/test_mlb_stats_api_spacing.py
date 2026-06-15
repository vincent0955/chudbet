"""Property-based and example tests for MLB Stats API inter-request spacing.

Exercises the request-spacing behavior of
:class:`app.mlb.stats_api_client.MLBStatsAPIClient`: across a sequence of
successful requests, consecutive issued requests are spaced by at least the
configured ``min_interval_sec`` (Req 6.6).

The client takes injectable ``monotonic`` and ``sleep`` callables. The test
drives it with a deterministic fake clock and a ``sleep`` spy that advances the
clock by the slept duration (modelling real wall-clock progress), plus a
recording transport that timestamps the moment each underlying request is
issued and advances the clock to simulate the request taking time. The property
then asserts the gap between consecutive issue timestamps is never less than the
configured minimum interval, regardless of how long the requests themselves take.

Feature: mlb-support, Property 10
Validates: Requirements 6.6
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.mlb.config import MLBClientConfig
from app.mlb.stats_api_client import MLBStatsAPIClient

# A generous (real-seconds) per-request timeout. The transport completes
# instantly in wall-clock terms, so the timeout never trips; only the *fake*
# clock advances during the test.
_TIMEOUT_SEC = 30.0


class _FakeClock:
    """Deterministic monotonic clock whose ``sleep`` advances time.

    A real :func:`time.sleep` advances wall-clock time, which a subsequent
    :func:`time.monotonic` would observe. The fake mirrors that: sleeping for
    ``secs`` advances the clock by exactly ``secs`` (never negative).
    """

    def __init__(self) -> None:
        self._now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._now

    def sleep(self, secs: float) -> None:
        # The client must never request a negative sleep.
        assert secs >= 0.0
        self.sleeps.append(secs)
        self._now += secs

    def advance(self, secs: float) -> None:
        self._now += secs


class _RecordingTransport:
    """Transport stub that records each request's issue time and returns valid data.

    Every call timestamps ``clock.monotonic()`` (the instant the request is
    issued) and then advances the clock by the next configured "work duration"
    to model the request taking wall-clock time before it returns.
    """

    def __init__(self, clock: _FakeClock, work_durations: list[float]) -> None:
        self._clock = clock
        self._work = iter(work_durations)
        self.issue_times: list[float] = []

    def _record_and_work(self) -> None:
        self.issue_times.append(self._clock.monotonic())
        try:
            duration = next(self._work)
        except StopIteration:
            duration = 0.0
        self._clock.advance(duration)

    def teams(self) -> dict:
        self._record_and_work()
        return {"teams": [{"id": 1}]}

    def roster(self, mlb_team_id: int) -> dict:
        self._record_and_work()
        return {"roster": [{"person": {"id": 1}}]}

    def schedule(self, start, end) -> list:
        self._record_and_work()
        return [{"game_id": 1}]

    def boxscore(self, mlb_game_id: int) -> dict:
        self._record_and_work()
        return {"home": {}, "away": {}}


# Strategies -----------------------------------------------------------------

# Configured minimum spacing, including 0 (the floor, where no spacing applies)
# and sub-second / multi-second values.
_min_interval_strategy = st.floats(
    min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False
)

# Which successful public method to issue on each step (spacing is
# method-independent, but varying the call exercises every public entry point).
_methods_strategy = st.lists(
    st.sampled_from(["teams", "roster", "schedule", "boxscore"]),
    min_size=2,
    max_size=8,
)

# Per-request wall-clock "work" durations (the request itself taking time);
# these may be shorter or longer than the configured spacing interval.
_work_strategy = st.lists(
    st.floats(min_value=0.0, max_value=15.0, allow_nan=False, allow_infinity=False),
    min_size=8,
    max_size=8,
)


def _invoke(client: MLBStatsAPIClient, method: str) -> None:
    if method == "teams":
        client.teams()
    elif method == "roster":
        client.roster(1)
    elif method == "schedule":
        from datetime import date

        client.schedule(date(2024, 4, 1), date(2024, 4, 2))
    else:
        client.boxscore(1)


# Property 10 (Req 6.6): consecutive requests are spaced by >= min interval ---


@settings(deadline=None, max_examples=200)
@given(
    min_interval=_min_interval_strategy,
    methods=_methods_strategy,
    work_durations=_work_strategy,
)
def test_property10_consecutive_requests_spaced_by_min_interval(
    min_interval: float, methods: list[str], work_durations: list[float]
) -> None:
    """**Validates: Requirements 6.6**

    Feature: mlb-support, Property 10

    For any sequence of successful MLB Stats API requests, the gap between the
    issue times of consecutive requests is at least the configured
    ``min_interval_sec`` -- regardless of how long each request takes to run.
    """
    clock = _FakeClock()
    transport = _RecordingTransport(clock, work_durations)
    config = MLBClientConfig(
        timeout_sec=_TIMEOUT_SEC,
        max_attempts=3,
        min_interval_sec=min_interval,
        backoff_base_sec=0.0,
    )
    client = MLBStatsAPIClient(
        config,
        transport=transport,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    for method in methods:
        _invoke(client, method)

    issue_times = transport.issue_times
    # Every requested call was issued exactly once (all succeed on first attempt).
    assert len(issue_times) == len(methods)

    for earlier, later in zip(issue_times, issue_times[1:]):
        gap = later - earlier
        # Spacing is at least the configured minimum (tiny tolerance for float math).
        assert gap >= min_interval - 1e-9


# Example anchors (non-Hypothesis) -------------------------------------------


class TestSpacingExamples:
    """Concrete spacing scenarios for the client (Req 6.6)."""

    def _client(self, clock: _FakeClock, transport: _RecordingTransport, *, interval):
        config = MLBClientConfig(
            timeout_sec=_TIMEOUT_SEC,
            max_attempts=3,
            min_interval_sec=interval,
            backoff_base_sec=0.0,
        )
        return MLBStatsAPIClient(
            config, transport=transport, sleep=clock.sleep, monotonic=clock.monotonic
        )

    def test_instant_requests_are_spaced_by_full_interval(self) -> None:
        # Requests that take no time still get spaced by the full interval.
        clock = _FakeClock()
        transport = _RecordingTransport(clock, [0.0, 0.0, 0.0])
        client = self._client(clock, transport, interval=1.0)

        client.teams()
        client.teams()
        client.teams()

        times = transport.issue_times
        assert times == [0.0, 1.0, 2.0]

    def test_long_requests_need_no_added_spacing(self) -> None:
        # When a request itself takes longer than the interval, the next request
        # is still spaced by at least the interval (here, by the work duration).
        clock = _FakeClock()
        transport = _RecordingTransport(clock, [5.0, 5.0])
        client = self._client(clock, transport, interval=1.0)

        client.teams()
        client.teams()

        times = transport.issue_times
        assert times[1] - times[0] >= 1.0

    def test_zero_interval_imposes_no_spacing_sleep(self) -> None:
        # A floored-to-zero interval performs no spacing sleeps.
        clock = _FakeClock()
        transport = _RecordingTransport(clock, [0.0, 0.0, 0.0])
        client = self._client(clock, transport, interval=0.0)

        client.teams()
        client.teams()
        client.teams()

        assert clock.sleeps == []
        assert transport.issue_times == [0.0, 0.0, 0.0]

    def test_first_request_is_not_delayed(self) -> None:
        # No spacing sleep precedes the very first request.
        clock = _FakeClock()
        transport = _RecordingTransport(clock, [0.0])
        client = self._client(clock, transport, interval=2.0)

        client.teams()

        assert transport.issue_times == [0.0]
        assert clock.sleeps == []
