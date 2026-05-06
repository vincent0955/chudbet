"""Rough game market pricing from historical team scores."""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    GameMarketsRead,
    GameMoneylineMarketRead,
    GameSpreadMarketRead,
    GameTotalMarketRead,
    GameRead,
)
from app.db.models import Game

LOOKBACK_GAMES = 10
BOOK_MARGIN = 0.14
DEFAULT_MARGIN_SIGMA = 12.0
DEFAULT_TOTAL_SIGMA = 18.0
DEFAULT_HOME_EDGE = 2.5
DEFAULT_TOTAL = 222.5


def _normal_cdf(x: float, mean: float, stddev: float) -> float:
    z = (x - mean) / (stddev * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def _sample_mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(max(var, 0.0))


def _round_half(n: float) -> float:
    return float(round(n - 0.5) + 0.5)


def _american_from_probability(p: float) -> str:
    p = min(max(p, 0.001), 0.999)
    if p >= 0.5:
        odds = -100.0 * p / (1.0 - p)
    else:
        odds = 100.0 * (1.0 - p) / p
    rounded = int(round(odds))
    return f"+{rounded}" if rounded > 0 else str(rounded)


def _apply_two_way_margin(p_a_fair: float, margin: float = BOOK_MARGIN) -> tuple[float, float]:
    overround = 1.0 + (margin / (2.0 + margin))
    p_a = p_a_fair * overround
    p_b = (1.0 - p_a_fair) * overround
    p_a = min(max(p_a, 0.001), 0.999)
    p_b = min(max(p_b, 0.001), 0.999)
    return p_a, p_b


def _team_score_history(session: Session, team_id: int, before_date) -> tuple[list[float], list[float]]:
    rows = session.scalars(
        select(Game)
        .where(
            Game.game_date < before_date,
            Game.home_score.is_not(None),
            Game.away_score.is_not(None),
            (Game.home_team_id == team_id) | (Game.away_team_id == team_id),
        )
        .order_by(Game.game_date.desc(), Game.id.desc())
        .limit(LOOKBACK_GAMES)
    ).all()
    points_for: list[float] = []
    points_against: list[float] = []
    for g in rows:
        if g.home_team_id == team_id:
            points_for.append(float(g.home_score or 0))
            points_against.append(float(g.away_score or 0))
        else:
            points_for.append(float(g.away_score or 0))
            points_against.append(float(g.home_score or 0))
    return points_for, points_against


def build_game_markets(session: Session, game: Game) -> GameMarketsRead:
    home_for, home_against = _team_score_history(session, game.home_team_id, game.game_date)
    away_for, away_against = _team_score_history(session, game.away_team_id, game.game_date)

    home_for_mu, _ = _sample_mean_std(home_for)
    home_against_mu, _ = _sample_mean_std(home_against)
    away_for_mu, _ = _sample_mean_std(away_for)
    away_against_mu, _ = _sample_mean_std(away_against)

    if not home_for or not away_for:
        proj_margin = DEFAULT_HOME_EDGE
        proj_total = DEFAULT_TOTAL
        margin_sigma = DEFAULT_MARGIN_SIGMA
        total_sigma = DEFAULT_TOTAL_SIGMA
    else:
        proj_home = home_for_mu * 0.55 + away_against_mu * 0.45
        proj_away = away_for_mu * 0.55 + home_against_mu * 0.45
        proj_margin = proj_home - proj_away
        proj_total = proj_home + proj_away
        margin_sigma = max(DEFAULT_MARGIN_SIGMA, 0.5 * (_sample_mean_std(home_for)[1] + _sample_mean_std(away_for)[1]))
        total_sigma = max(DEFAULT_TOTAL_SIGMA, _sample_mean_std(home_for + away_for)[1])

    spread_home_line = _round_half(-proj_margin)
    total_line = _round_half(proj_total)

    p_home_ml_fair = 1.0 - _normal_cdf(0.0, proj_margin, margin_sigma)
    p_home_ml, p_away_ml = _apply_two_way_margin(min(max(p_home_ml_fair, 0.02), 0.98))

    p_home_spread_fair = 1.0 - _normal_cdf(-spread_home_line, proj_margin, margin_sigma)
    p_home_spread, p_away_spread = _apply_two_way_margin(min(max(p_home_spread_fair, 0.02), 0.98))

    p_over_fair = 1.0 - _normal_cdf(total_line, proj_total, total_sigma)
    p_over, p_under = _apply_two_way_margin(min(max(p_over_fair, 0.02), 0.98))

    return GameMarketsRead(
        game=GameRead.model_validate(game),
        lookback=LOOKBACK_GAMES,
        sample_games_home=len(home_for),
        sample_games_away=len(away_for),
        moneyline=GameMoneylineMarketRead(
            home_american=_american_from_probability(p_home_ml),
            away_american=_american_from_probability(p_away_ml),
        ),
        spread=GameSpreadMarketRead(
            home_line=spread_home_line,
            home_american=_american_from_probability(p_home_spread),
            away_line=-spread_home_line,
            away_american=_american_from_probability(p_away_spread),
        ),
        total=GameTotalMarketRead(
            line=total_line,
            over_american=_american_from_probability(p_over),
            under_american=_american_from_probability(p_under),
        ),
    )

