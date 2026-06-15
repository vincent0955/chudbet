"""League-neutral odds math shared across sport pricers.

Pure probability/odds helpers with no league-specific identifiers, constants, or
sport-keyed branching. These are reused by every sport's game-market and
prop-line pricers so the conversion math lives in exactly one place.
"""

from __future__ import annotations

import math

from app.core.config import get_book_margin

BOOK_MARGIN = get_book_margin()


def normal_cdf(x: float, mean: float, stddev: float) -> float:
    """Cumulative distribution function of a normal distribution at ``x``."""
    z = (x - mean) / (stddev * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def american_from_probability(p: float) -> str:
    """Convert an implied probability to an American-odds string.

    The probability is clamped to ``[0.001, 0.999]`` so the conversion always
    yields finite odds.
    """
    p = min(max(p, 0.001), 0.999)
    if p >= 0.5:
        odds = -100.0 * p / (1.0 - p)
    else:
        odds = 100.0 * (1.0 - p) / p
    rounded = int(round(odds))
    return f"+{rounded}" if rounded > 0 else str(rounded)


def apply_two_way_margin(p_a_fair: float, margin: float = BOOK_MARGIN) -> tuple[float, float]:
    """Apply a house margin to a fair two-way market, clamping each side.

    Each side's implied probability is scaled by the overround and then clamped
    independently to ``[0.001, 0.999]``.
    """
    overround = 1.0 + (margin / (2.0 + margin))
    p_a = p_a_fair * overround
    p_b = (1.0 - p_a_fair) * overround
    p_a = min(max(p_a, 0.001), 0.999)
    p_b = min(max(p_b, 0.001), 0.999)
    return p_a, p_b


def apply_two_way_margin_balanced(
    p_over_fair: float, margin: float = BOOK_MARGIN
) -> tuple[float, float]:
    """Apply a house margin to a fair two-way market, redistributing on saturation.

    When one side saturates at the maximum, the remaining overround is assigned
    to the opposite side so the two implied probabilities still reflect the full
    overround. Calibrated so with ``margin=0.14`` a 50/50 market prices to
    -114/-114.
    """
    overround = 1.0 + (margin / (2.0 + margin))
    p_over = p_over_fair * overround
    p_under = (1.0 - p_over_fair) * overround

    # Guardrails for extreme tails.
    max_side = 0.999
    min_side = 0.001
    if p_over >= max_side:
        p_over = max_side
        p_under = max(min_side, min(max_side, overround - p_over))
    elif p_under >= max_side:
        p_under = max_side
        p_over = max(min_side, min(max_side, overround - p_under))
    else:
        p_over = max(min_side, p_over)
        p_under = max(min_side, p_under)

    return (p_over, p_under)
