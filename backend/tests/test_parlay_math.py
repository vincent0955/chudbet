"""Unit tests for the normal-approximation parlay math helpers."""

from __future__ import annotations

import math
import random

import pytest

from app.db.enums import LegDirection
from app.parlay.math import (
    fair_decimal_odds,
    joint_probability_standard,
    joint_probability_x_of_y,
    leg_win_probability,
    phi,
    sample_mean_std,
)


class TestPhi:
    def test_phi_at_zero_is_half(self) -> None:
        assert phi(0.0) == pytest.approx(0.5)

    def test_phi_is_symmetric(self) -> None:
        assert phi(1.5) + phi(-1.5) == pytest.approx(1.0)

    def test_phi_one_sigma(self) -> None:
        assert phi(1.0) == pytest.approx(0.8413447, abs=1e-6)

    def test_phi_is_monotonic(self) -> None:
        assert phi(-2.0) < phi(0.0) < phi(2.0)


class TestLegWinProbability:
    def test_over_when_mean_above_line(self) -> None:
        # mean equal to line => exactly 0.5 for OVER
        assert leg_win_probability(20.0, 20.0, 5.0, LegDirection.OVER) == pytest.approx(0.5)

    def test_over_and_under_are_complements(self) -> None:
        over = leg_win_probability(18.0, 22.0, 6.0, LegDirection.OVER)
        under = leg_win_probability(18.0, 22.0, 6.0, LegDirection.UNDER)
        assert over + under == pytest.approx(1.0)

    def test_higher_mean_increases_over_probability(self) -> None:
        low = leg_win_probability(20.0, 18.0, 5.0, LegDirection.OVER)
        high = leg_win_probability(20.0, 25.0, 5.0, LegDirection.OVER)
        assert high > low

    def test_zero_sigma_is_deterministic_over(self) -> None:
        assert leg_win_probability(20.0, 25.0, 0.0, LegDirection.OVER) == 1.0
        assert leg_win_probability(20.0, 15.0, 0.0, LegDirection.OVER) == 0.0

    def test_zero_sigma_is_deterministic_under(self) -> None:
        assert leg_win_probability(20.0, 15.0, 0.0, LegDirection.UNDER) == 1.0
        assert leg_win_probability(20.0, 25.0, 0.0, LegDirection.UNDER) == 0.0

    def test_zero_sigma_on_the_line_is_loss(self) -> None:
        assert leg_win_probability(20.0, 20.0, 0.0, LegDirection.OVER) == 0.0
        assert leg_win_probability(20.0, 20.0, 0.0, LegDirection.UNDER) == 0.0

    def test_result_always_in_unit_interval(self) -> None:
        p = leg_win_probability(5.0, 50.0, 1.0, LegDirection.OVER)
        assert 0.0 <= p <= 1.0


class TestSampleMeanStd:
    def test_basic_mean_and_std(self) -> None:
        mean, std = sample_mean_std([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        assert mean == pytest.approx(5.0)
        assert std == pytest.approx(2.13808993, abs=1e-6)

    def test_requires_at_least_two_values(self) -> None:
        with pytest.raises(ValueError):
            sample_mean_std([3.0])

    def test_identical_values_have_zero_std(self) -> None:
        mean, std = sample_mean_std([7.0, 7.0, 7.0])
        assert mean == pytest.approx(7.0)
        assert std == 0.0


class TestJointProbabilityStandard:
    def test_multiplies_independent_legs(self) -> None:
        assert joint_probability_standard([0.5, 0.5]) == pytest.approx(0.25)

    def test_empty_is_one(self) -> None:
        assert joint_probability_standard([]) == 1.0

    def test_clamps_out_of_range_inputs(self) -> None:
        assert joint_probability_standard([1.5, 0.5]) == pytest.approx(0.5)
        assert joint_probability_standard([-0.2, 0.5]) == 0.0


class TestJointProbabilityXOfY:
    def test_all_certain_legs_always_hit(self) -> None:
        rng = random.Random(1)
        p = joint_probability_x_of_y([1.0, 1.0, 1.0], k_required=2, iterations=500, rng=rng)
        assert p == 1.0

    def test_impossible_legs_never_hit(self) -> None:
        rng = random.Random(1)
        p = joint_probability_x_of_y([0.0, 0.0], k_required=1, iterations=500, rng=rng)
        assert p == 0.0

    def test_monte_carlo_is_close_to_analytic(self) -> None:
        # P(at least 1 of two 0.5 legs) = 0.75
        rng = random.Random(42)
        p = joint_probability_x_of_y([0.5, 0.5], k_required=1, iterations=50_000, rng=rng)
        assert p == pytest.approx(0.75, abs=0.02)

    def test_deterministic_for_fixed_seed(self) -> None:
        a = joint_probability_x_of_y([0.4, 0.6, 0.5], 2, 2000, random.Random(7))
        b = joint_probability_x_of_y([0.4, 0.6, 0.5], 2, 2000, random.Random(7))
        assert a == b

    def test_invalid_k_raises(self) -> None:
        with pytest.raises(ValueError):
            joint_probability_x_of_y([0.5, 0.5], k_required=0, iterations=10, rng=random.Random())
        with pytest.raises(ValueError):
            joint_probability_x_of_y([0.5, 0.5], k_required=3, iterations=10, rng=random.Random())

    def test_non_positive_iterations_raises(self) -> None:
        with pytest.raises(ValueError):
            joint_probability_x_of_y([0.5], k_required=1, iterations=0, rng=random.Random())


class TestFairDecimalOdds:
    def test_inverse_of_probability(self) -> None:
        assert fair_decimal_odds(0.25) == pytest.approx(4.0)
        assert fair_decimal_odds(0.5) == pytest.approx(2.0)

    def test_zero_probability_returns_none(self) -> None:
        assert fair_decimal_odds(0.0) is None

    def test_negative_probability_returns_none(self) -> None:
        assert fair_decimal_odds(-0.1) is None
