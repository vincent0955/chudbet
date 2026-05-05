"""Normal approximation for stat vs line + independent leg combination."""

from __future__ import annotations

import math
import random
from statistics import mean, stdev

from app.db.enums import LegDirection


def phi(z: float) -> float:
    """Standard normal CDF Φ(z)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def leg_win_probability(
    line: float,
    mu: float,
    sigma: float,
    direction: LegDirection,
) -> float:
    """
    Approximate P(leg wins) assuming the stat ~ N(mu, sigma²).

    OVER  => P(stat > line); UNDER => P(stat < line).
    """
    if sigma <= 0:
        if direction == LegDirection.OVER:
            return 1.0 if mu > line else 0.0
        return 1.0 if mu < line else 0.0

    z = (line - mu) / sigma
    if direction == LegDirection.OVER:
        return max(0.0, min(1.0, 1.0 - phi(z)))
    return max(0.0, min(1.0, phi(z)))


def sample_mean_std(values: list[float]) -> tuple[float, float]:
    """Sample mean and (sample) standard deviation (ddof=1)."""
    if len(values) < 2:
        raise ValueError("need at least 2 games for standard deviation")
    m = mean(values)
    s = stdev(values)
    return m, s if s > 0 else 0.0


def joint_probability_standard(leg_probs: list[float]) -> float:
    """Independent-product probability for a standard (all-legs) parlay."""
    p = 1.0
    for x in leg_probs:
        p *= max(0.0, min(1.0, x))
    return max(0.0, min(1.0, p))


def joint_probability_x_of_y(
    leg_probs: list[float],
    k_required: int,
    iterations: int,
    rng: random.Random,
) -> float:
    """Monte Carlo P(at least k legs hit) assuming independent Bernoulli legs."""
    n = len(leg_probs)
    if k_required < 1 or k_required > n:
        raise ValueError("invalid k_required")
    if iterations < 1:
        raise ValueError("iterations must be positive")

    wins = 0
    ps = [max(0.0, min(1.0, p)) for p in leg_probs]
    for _ in range(iterations):
        hits = sum(1 for p in ps if rng.random() < p)
        if hits >= k_required:
            wins += 1
    return wins / iterations


def fair_decimal_odds(joint_p: float) -> float | None:
    if joint_p <= 0:
        return None
    return 1.0 / joint_p
