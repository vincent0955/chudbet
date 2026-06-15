"""Property test for MLB worker ingest-interval validation.

Feature: mlb-support, Property 12
Validates: Requirements 7.2, 7.3, 7.4
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.mlb.config import classify_worker_ingest_interval

_int_strategy = st.integers(min_value=-100_000, max_value=200_000)
_raw_strategy = st.one_of(
    _int_strategy.map(str),
    st.text(min_size=0, max_size=32),
)


@settings(deadline=None, max_examples=200)
@given(raw=_raw_strategy)
def test_property12_worker_interval_classifies_every_value(raw: str) -> None:
    """**Validates: Requirements 7.2, 7.3, 7.4**

    Feature: mlb-support, Property 12

    Every configured ingest-interval value is classified as exactly one of:
    schedule (1–86400), idle (0), or invalid (negative / non-numeric / >86400).
    """
    result = classify_worker_ingest_interval(raw)
    stripped = raw.strip()

    try:
        value = int(stripped)
        numeric = True
    except ValueError:
        numeric = False

    if not stripped or not numeric or value < 0 or value > 86400:
        assert result.mode == "invalid"
        assert result.seconds is None
        return

    if value == 0:
        assert result.mode == "idle"
        assert result.seconds is None
        return

    assert result.mode == "schedule"
    assert result.seconds == value
