"""Property-based and example tests for MLB Stats API client configuration.

Exercises :func:`app.mlb.config.get_api_timeout_sec`, the getter that reads the
``MLB_API_TIMEOUT_SEC`` environment variable and clamps it to the allowed
per-request timeout range.

Feature: mlb-support, Property 8
Validates: Requirements 6.2
"""

from __future__ import annotations

import os
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.mlb import config

# The allowed per-request timeout range and default (Req 6.2).
_MIN = config.API_TIMEOUT_MIN_SEC  # 1
_MAX = config.API_TIMEOUT_MAX_SEC  # 60
_DEFAULT = config.API_TIMEOUT_DEFAULT_SEC  # 10


# Strategies -----------------------------------------------------------------

# Arbitrary finite numeric inputs spanning well below, within, and well above
# the [1, 60] range, including negatives and zero.
_numeric_strategy = st.floats(
    min_value=-1000.0,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
)


# Property 8 (Req 6.2): timeout is clamped to its allowed range --------------


@settings(deadline=None, max_examples=200)
@given(raw_value=_numeric_strategy)
def test_property8_timeout_clamped_to_range(raw_value: float) -> None:
    """**Validates: Requirements 6.2**

    Feature: mlb-support, Property 8

    For any numeric ``MLB_API_TIMEOUT_SEC`` input, the configured per-request
    timeout is always within the inclusive ``[1, 60]`` range. When the input
    already falls inside the range it is returned unchanged; when it is below
    the minimum or above the maximum it is pinned to the respective bound.
    """
    # ``mock.patch.dict`` (rather than the function-scoped ``monkeypatch``
    # fixture) sets/restores the env var on every generated example.
    with mock.patch.dict(os.environ, {"MLB_API_TIMEOUT_SEC": repr(raw_value)}):
        result = config.get_api_timeout_sec()

    # Always within the allowed range (Req 6.2).
    assert _MIN <= result <= _MAX

    # The clamp is order-preserving: identity inside the range, pin outside it.
    if raw_value < _MIN:
        assert result == _MIN
    elif raw_value > _MAX:
        assert result == _MAX
    else:
        assert result == raw_value


# Example anchors (non-Hypothesis) -------------------------------------------


class TestTimeoutClampingExamples:
    """Concrete edge cases for the per-request timeout getter (Req 6.2)."""

    def test_defaults_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MLB_API_TIMEOUT_SEC", raising=False)
        assert config.get_api_timeout_sec() == _DEFAULT

    def test_defaults_when_blank(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLB_API_TIMEOUT_SEC", "   ")
        assert config.get_api_timeout_sec() == _DEFAULT

    def test_defaults_when_non_numeric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLB_API_TIMEOUT_SEC", "not-a-number")
        assert config.get_api_timeout_sec() == _DEFAULT

    def test_below_minimum_clamps_to_min(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLB_API_TIMEOUT_SEC", "0.5")
        assert config.get_api_timeout_sec() == _MIN

    def test_negative_clamps_to_min(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLB_API_TIMEOUT_SEC", "-30")
        assert config.get_api_timeout_sec() == _MIN

    def test_above_maximum_clamps_to_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLB_API_TIMEOUT_SEC", "120")
        assert config.get_api_timeout_sec() == _MAX

    def test_within_range_passes_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLB_API_TIMEOUT_SEC", "25")
        assert config.get_api_timeout_sec() == 25.0

    def test_boundaries_are_inclusive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLB_API_TIMEOUT_SEC", "1")
        assert config.get_api_timeout_sec() == _MIN
        monkeypatch.setenv("MLB_API_TIMEOUT_SEC", "60")
        assert config.get_api_timeout_sec() == _MAX
