"""Create parlays using the server-authoritative pricing engine."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.api.parlay_schemas import ParlayCreate
from app.core.config import get_book_margin
from app.db.enums import ParlayMode, StatType
from app.db.models import Game, Parlay, ParlayGameLeg, ParlayLeg, PlayerGameStat
from app.parlay import pricing


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
    """Price the ticket server-side, then insert `Parlay`/`ParlayLeg` rows (no commit).

    All authoritative lines, odds, and probabilities come from
    ``pricing.price_ticket``, which also enforces the pre-game gate, line-drift
    tolerance, and authoritative line/odds substitution. Any ``PricingError`` /
    ``ValueError`` it raises propagates to the route handlers.
    """
    legs_in = body.legs
    game_legs_in = body.game_legs
    n = len(legs_in) + len(game_legs_in)

    priced = pricing.price_ticket(session, body)

    meta: dict[str, Any] = {
        "lookback_games": body.lookback_games,
        "model": "server_authoritative_v1",
        "wager_on_hit": body.wager_on_hit,
        "book_margin": get_book_margin(),
        "payout_decimal_odds": priced.payout_decimal_odds,
    }
    if body.mode == ParlayMode.X_OF_Y:
        meta["simulation_iterations"] = body.simulation_iterations
        meta["rng_seed"] = body.rng_seed

    parlay = Parlay(
        mode=body.mode,
        k_required=body.k_required if body.mode == ParlayMode.X_OF_Y else None,
        total_legs=n,
        p_hit=priced.p_hit,
        wager_on_hit=body.wager_on_hit,
        fair_decimal_odds=priced.fair_decimal_odds,
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
                line=priced.player_legs[i].line,
                direction=leg.direction,
                leg_probability=priced.player_legs[i].probability,
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
                line=priced.game_legs[i].line,
                odds_american=priced.game_legs[i].odds_american,
                leg_probability=priced.game_legs[i].probability,
                sort_order=len(legs_in) + i,
            )
        )

    session.flush()
    session.refresh(parlay)
    return parlay
