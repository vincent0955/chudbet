"""Property-based and example tests for the pure pricing helpers.

These exercise the odds-math primitives in :mod:`app.parlay.pricing` that have
no database dependency: ``apply_house_margin``, ``devig_two_way``,
``american_to_decimal`` and ``implied_prob_from_american``, plus the floor-based
return-rounding invariant used by ``money.place_wager``.

Validates design Properties 1, 2, 3, 7.
Requirements: 2.4, 2.5, 4.4, 5.1, 5.3, 5.4, 8.2.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.parlay.pricing import (
    american_to_decimal,
    apply_house_margin,
    devig_two_way,
    implied_prob_from_american,
)

# Strategies -----------------------------------------------------------------

# Fair decimal odds live in (1.0, 1e6]. Start just above 1.0 so that the
# guarantee "payout strictly > 1" is meaningful (a fair_decimal of exactly 1.0
# represents a certain outcome with no payout).
fair_decimals = st.floats(
    min_value=1.0000001,
    max_value=1_000_000,
    allow_nan=False,
    allow_infinity=False,
)

# House margin as a fraction in [0, 1].
margins = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Non-zero American odds.
american_odds = st.integers(min_value=-10_000, max_value=10_000).filter(lambda x: x != 0)

# Stake amounts in cents: 1 cent up to $50,000.
stake_cents_strategy = st.integers(min_value=1, max_value=50_000_00)

# Small absolute tolerance for float comparisons.
_EPS = 1e-9


# Property 1 (Req 2.5, 5.1, 5.3): margined payout stays in (1, fair] ----------


@settings(deadline=None)
@given(fair=fair_decimals, margin=margins)
def test_property1_margined_payout_in_open_interval(fair: float, margin: float) -> None:
    """**Validates: Requirements 2.5, 5.1, 5.3**

    For any fair_decimal > 1 and margin in [0, 1], the margined payout is
    strictly greater than 1.0 (a winning bet always pays) and never exceeds the
    fair odds.
    """
    payout = apply_house_margin(fair, margin)
    assert 1.0 < payout <= fair + _EPS


# Property 2 (Req 5.1, 5.4): payout is monotonically non-increasing in margin --


@settings(deadline=None)
@given(fair=fair_decimals, m_a=margins, m_b=margins)
def test_property2_payout_monotonic_in_margin(fair: float, m_a: float, m_b: float) -> None:
    """**Validates: Requirements 5.1, 5.4**

    A larger margin never produces a larger payout, and both payouts remain
    bounded by the fair odds.
    """
    m1, m2 = sorted((m_a, m_b))  # m1 <= m2
    payout_low_margin = apply_house_margin(fair, m1)
    payout_high_margin = apply_house_margin(fair, m2)

    assert payout_high_margin <= payout_low_margin + _EPS
    assert payout_low_margin <= fair + _EPS
    assert payout_high_margin <= fair + _EPS


# Property 3 (Req 4.4): de-vig yields a valid two-way distribution ------------


@settings(deadline=None)
@given(american_a=american_odds, american_b=american_odds)
def test_property3_devig_two_way_distribution(american_a: int, american_b: int) -> None:
    """**Validates: Requirements 4.4**

    De-vigging a two-way market produces probabilities strictly inside (0, 1)
    that sum to 1.0.
    """
    p_a, p_b = devig_two_way(american_a, american_b)

    assert 0.0 < p_a < 1.0
    assert 0.0 < p_b < 1.0
    assert p_a + p_b == pytest.approx(1.0)


# Property 7 (Req 2.4, 8.2): floor-based return rounding -----------------------


@settings(deadline=None)
@given(
    stake_cents=stake_cents_strategy,
    fair=fair_decimals,
    margin=margins,
)
def test_property7_return_rounding_floor_invariant(
    stake_cents: int, fair: float, margin: float
) -> None:
    """**Validates: Requirements 2.4, 8.2**

    The integer return computed via ``math.floor(stake_cents * payout)`` is a
    non-negative integer that never exceeds the exact (unrounded) return. This
    mirrors the floor logic in ``money.place_wager``.
    """
    payout = apply_house_margin(fair, margin)
    ret = math.floor(stake_cents * payout)

    assert isinstance(ret, int)
    assert ret >= 0
    assert ret <= stake_cents * payout + 1e-6


# Concrete sanity anchors (non-Hypothesis) ------------------------------------


def test_example_apply_house_margin_reduces_even_money() -> None:
    payout = apply_house_margin(2.0, 0.14)
    assert 1.0 < payout < 2.0


def test_example_devig_symmetric_market_is_even() -> None:
    p_a, p_b = devig_two_way(-110, -110)
    assert p_a == pytest.approx(0.5)
    assert p_b == pytest.approx(0.5)


def test_example_american_to_decimal_plus_150() -> None:
    assert american_to_decimal(150) == pytest.approx(2.5)


def test_example_implied_prob_symmetry() -> None:
    # +100 and -100 both imply a 0.5 win probability.
    assert implied_prob_from_american(100) == pytest.approx(0.5)
    assert implied_prob_from_american(-100) == pytest.approx(0.5)
