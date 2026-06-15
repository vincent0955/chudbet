"""MLB game-market pricing (Requirement 8).

Computes moneyline, run line, and total runs markets for an MLB game from the
two teams' prior MLB-game run totals. This module is the baseball analogue of
``app.services.game_markets`` and uses **baseball** constants only -- it never
imports the NBA basketball pricing constants. The sport-agnostic odds math is
imported from the shared league-neutral ``app.services.odds_math`` helper.

Pricing rules (Req 8.1-8.6):

- Moneyline: two American prices, one for the home side and one for the away
  side (Req 8.1).
- Run line: home/away lines equal in magnitude, opposite in sign, expressed as a
  half-run value (``MLB_RUN_LINE`` = 1.5), each with an American price. The run
  line reuses the shared ``GameMarketType.SPREAD`` vocabulary so shared
  persistence/settlement need no new enum values; the "Run Line" label is a
  frontend concern (Req 8.2).
- Total runs: a single positive half-run total line with over/under prices
  (Req 8.3).
- Projections derive only from the two teams' prior MLB-game run totals within
  ``MLB_LOOKBACK_GAMES``, scoped to ``sport=MLB`` and excluding the target game
  (Req 8.4).
- The configured house margin is applied so each two-way market's implied
  probabilities sum to strictly more than 1 (Req 8.5).
- A team with fewer prior MLB games than ``MLB_MIN_SAMPLE`` falls back to the
  configured baseball default projections (Req 8.6).
"""

from __future__ import annotations

import math
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    GameMarketsRead,
    GameMoneylineMarketRead,
    GameRead,
    GameSpreadMarketRead,
    GameTotalMarketRead,
)
from app.db.enums import Sport
from app.db.models import Game
from app.mlb.config import get_game_lookback, get_game_min_samples
from app.services.odds_math import (
    american_from_probability,
    apply_two_way_margin,
    normal_cdf,
)

# --- Baseball pricing constants (no basketball constants are used here) ---
MLB_LOOKBACK_GAMES = get_game_lookback()  # prior MLB games sampled per team
MLB_MIN_SAMPLE = get_game_min_samples()   # min prior games before defaults apply
MLB_DEFAULT_TOTAL = 8.5                    # baseball default total runs (half-run)
MLB_DEFAULT_HOME_EDGE = 0.15               # baseball default home run-margin edge
MLB_RUN_LINE = 1.5                         # standard half-run run-line magnitude
MLB_MARGIN_SIGMA = 4.0                     # baseball run-margin dispersion
MLB_TOTAL_SIGMA = 4.5                      # baseball total-runs dispersion

_PROB_FLOOR = 0.02
_PROB_CEIL = 0.98


def _sample_mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(max(var, 0.0))


def _round_half(n: float) -> float:
    """Round to the nearest half-integer (``x.5``)."""
    return float(round(n - 0.5) + 0.5)


def _team_run_history(
    session: Session, team_id: int, before_date: date, exclude_game_id: int
) -> tuple[list[float], list[float]]:
    """Return (runs_for, runs_against) over prior MLB games for a team.

    Scoped to ``sport=MLB``, restricted to games before ``before_date`` with
    final run totals, and explicitly excluding the target game (Req 8.4).
    """
    rows = session.scalars(
        select(Game)
        .where(
            Game.sport == Sport.MLB,
            Game.id != exclude_game_id,
            Game.game_date < before_date,
            Game.home_score.is_not(None),
            Game.away_score.is_not(None),
            (Game.home_team_id == team_id) | (Game.away_team_id == team_id),
        )
        .order_by(Game.game_date.desc(), Game.id.desc())
        .limit(MLB_LOOKBACK_GAMES)
    ).all()
    runs_for: list[float] = []
    runs_against: list[float] = []
    for g in rows:
        if g.home_team_id == team_id:
            runs_for.append(float(g.home_score or 0))
            runs_against.append(float(g.away_score or 0))
        else:
            runs_for.append(float(g.away_score or 0))
            runs_against.append(float(g.home_score or 0))
    return runs_for, runs_against


def _clamp_fair(p: float) -> float:
    return min(max(p, _PROB_FLOOR), _PROB_CEIL)


def build_mlb_game_markets(session: Session, game: Game) -> GameMarketsRead:
    """Build MLB moneyline, run line, and total runs markets for ``game``."""
    home_for, home_against = _team_run_history(
        session, game.home_team_id, game.game_date, game.id
    )
    away_for, away_against = _team_run_history(
        session, game.away_team_id, game.game_date, game.id
    )

    home_for_mu, _ = _sample_mean_std(home_for)
    home_against_mu, _ = _sample_mean_std(home_against)
    away_for_mu, _ = _sample_mean_std(away_for)
    away_against_mu, _ = _sample_mean_std(away_against)

    # Fall back to baseball defaults when either team is below the min sample.
    if len(home_for) < MLB_MIN_SAMPLE or len(away_for) < MLB_MIN_SAMPLE:
        proj_margin = MLB_DEFAULT_HOME_EDGE
        proj_total = MLB_DEFAULT_TOTAL
        margin_sigma = MLB_MARGIN_SIGMA
        total_sigma = MLB_TOTAL_SIGMA
    else:
        proj_home = home_for_mu * 0.55 + away_against_mu * 0.45
        proj_away = away_for_mu * 0.55 + home_against_mu * 0.45
        proj_margin = proj_home - proj_away
        proj_total = proj_home + proj_away
        margin_sigma = max(
            MLB_MARGIN_SIGMA,
            0.5 * (_sample_mean_std(home_for)[1] + _sample_mean_std(away_for)[1]),
        )
        total_sigma = max(MLB_TOTAL_SIGMA, _sample_mean_std(home_for + away_for)[1])

    # Run line: favorite gets the negative half-run, underdog the positive.
    run_line_home = -MLB_RUN_LINE if proj_margin >= 0 else MLB_RUN_LINE
    total_line = max(MLB_RUN_LINE, _round_half(proj_total))

    # Moneyline: probability the home side wins outright (margin > 0).
    p_home_ml_fair = 1.0 - normal_cdf(0.0, proj_margin, margin_sigma)
    p_home_ml, p_away_ml = apply_two_way_margin(_clamp_fair(p_home_ml_fair))

    # Run line: home covers when margin > -home_line.
    p_home_rl_fair = 1.0 - normal_cdf(-run_line_home, proj_margin, margin_sigma)
    p_home_rl, p_away_rl = apply_two_way_margin(_clamp_fair(p_home_rl_fair))

    # Total: over when total > line.
    p_over_fair = 1.0 - normal_cdf(total_line, proj_total, total_sigma)
    p_over, p_under = apply_two_way_margin(_clamp_fair(p_over_fair))

    return GameMarketsRead(
        game=GameRead.model_validate(game),
        lookback=MLB_LOOKBACK_GAMES,
        sample_games_home=len(home_for),
        sample_games_away=len(away_for),
        moneyline=GameMoneylineMarketRead(
            home_american=american_from_probability(p_home_ml),
            away_american=american_from_probability(p_away_ml),
        ),
        spread=GameSpreadMarketRead(
            home_line=run_line_home,
            home_american=american_from_probability(p_home_rl),
            away_line=-run_line_home,
            away_american=american_from_probability(p_away_rl),
        ),
        total=GameTotalMarketRead(
            line=total_line,
            over_american=american_from_probability(p_over),
            under_american=american_from_probability(p_under),
        ),
    )
