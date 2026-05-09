"""Create parlays from DB history + normal approximation."""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.api.parlay_schemas import ParlayCreate
from app.db.enums import ParlayMode, StatType
from app.db.models import Game, Parlay, ParlayGameLeg, ParlayLeg, Player, PlayerGameStat
from app.parlay.math import (
    fair_decimal_odds,
    joint_probability_standard,
    joint_probability_x_of_y,
    leg_win_probability,
    sample_mean_std,
)
from app.services.game_wager_gate import require_pre_game_game_for_wager


def _stat_column(stat: StatType):
    return {
        StatType.PTS: PlayerGameStat.points,
        StatType.REB: PlayerGameStat.rebounds,
        StatType.AST: PlayerGameStat.assists,
    }[stat]


def fetch_stat_series(
    session: Session,
    player_id: int,
    stat: StatType,
    lookback: int,
) -> list[float]:
    col = _stat_column(stat)
    stmt: Select[Any] = (
        select(col)
        .select_from(PlayerGameStat)
        .join(Game, PlayerGameStat.game_id == Game.id)
        .where(PlayerGameStat.player_id == player_id)
        .order_by(Game.game_date.desc(), Game.id.desc())
        .limit(lookback)
    )
    rows = session.scalars(stmt).all()
    return [float(v) for v in rows]


def create_parlay(session: Session, body: ParlayCreate) -> Parlay:
    """Compute leg and joint probabilities; insert `Parlay` and `ParlayLeg` rows (no commit)."""
    legs_in = body.legs
    game_legs_in = body.game_legs
    n = len(legs_in) + len(game_legs_in)

    leg_probs: list[float] = []
    game_leg_probs: list[float] = []
    leg_histories: list[dict[str, Any]] = []

    for leg in legs_in:
        player = session.get(Player, leg.player_id)
        if player is None:
            raise ValueError(f"player_id {leg.player_id} not found")

        if leg.game_id is not None:
            game = session.get(Game, leg.game_id)
            if game is None:
                raise ValueError(f"game_id {leg.game_id} not found")
            require_pre_game_game_for_wager(game)

        series = fetch_stat_series(session, leg.player_id, leg.stat_type, body.lookback_games)
        if len(series) < 2:
            raise ValueError(
                f"need at least 2 games of history for player {leg.player_id} "
                f"({leg.stat_type}); got {len(series)}",
            )

        mu, sigma = sample_mean_std(series)
        p = leg_win_probability(leg.line, mu, sigma, leg.direction)
        leg_probs.append(p)
        leg_histories.append({"mu": mu, "sigma": sigma, "games_used": len(series)})

    def _prob_from_american(american: int) -> float:
        if american > 0:
            return 100.0 / (american + 100.0)
        return abs(american) / (abs(american) + 100.0)

    for leg in game_legs_in:
        game = session.get(Game, leg.game_id)
        if game is None:
            raise ValueError(f"game_id {leg.game_id} not found")
        require_pre_game_game_for_wager(game)
        game_leg_probs.append(_prob_from_american(leg.odds_american))

    rng = random.Random(body.rng_seed)
    all_leg_probs = leg_probs + game_leg_probs
    if body.mode == ParlayMode.STANDARD:
        p_hit = joint_probability_standard(all_leg_probs)
    else:
        p_hit = joint_probability_x_of_y(
            all_leg_probs,
            body.k_required,  # type: ignore[arg-type]
            body.simulation_iterations,
            rng,
        )

    p_ticket = p_hit if body.wager_on_hit else (1.0 - p_hit)
    fair = fair_decimal_odds(p_ticket)

    meta: dict[str, Any] = {
        "lookback_games": body.lookback_games,
        "model": "normal_approx_player_props_plus_implied_game_legs",
        "leg_history": leg_histories,
        "game_leg_model": "implied_probability_from_odds_american",
        "wager_on_hit": body.wager_on_hit,
    }
    if body.mode == ParlayMode.X_OF_Y:
        meta["simulation_iterations"] = body.simulation_iterations
        meta["rng_seed"] = body.rng_seed

    parlay = Parlay(
        mode=body.mode,
        k_required=body.k_required if body.mode == ParlayMode.X_OF_Y else None,
        total_legs=n,
        p_hit=p_hit,
        wager_on_hit=body.wager_on_hit,
        fair_decimal_odds=fair,
        metadata_json=meta,
    )
    session.add(parlay)
    session.flush()

    for i, leg in enumerate(legs_in):
        session.add(
            ParlayLeg(
                parlay_id=parlay.id,
                player_id=leg.player_id,
                game_id=leg.game_id,
                stat_type=leg.stat_type,
                line=leg.line,
                direction=leg.direction,
                leg_probability=leg_probs[i],
                sort_order=i,
            )
        )

    for i, leg in enumerate(game_legs_in):
        session.add(
            ParlayGameLeg(
                parlay_id=parlay.id,
                game_id=leg.game_id,
                market_type=leg.market_type,
                selection=leg.selection,
                line=leg.line,
                odds_american=leg.odds_american,
                leg_probability=game_leg_probs[i],
                sort_order=len(legs_in) + i,
            )
        )

    session.flush()
    session.refresh(parlay)
    return parlay
