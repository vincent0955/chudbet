"""Build API parlay payloads with per-leg display fields (outcomes, names)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.parlay_schemas import ParlayGameLegRead, ParlayLegRead, ParlayRead
from app.db.enums import StatType
from app.db.models import Game, Parlay, ParlayGameLeg, ParlayLeg, Player, PlayerGameStat
from app.db.enums import WagerStatus
from app.services.settlement import game_leg_ui_outcome, leg_ui_outcome


def parlay_detail_load_options():
    """ORM loader tuple for parlays returned to clients with leg display."""
    return (
        selectinload(Parlay.legs).selectinload(ParlayLeg.player).selectinload(Player.team),
        selectinload(Parlay.legs).selectinload(ParlayLeg.game).selectinload(Game.home_team),
        selectinload(Parlay.legs).selectinload(ParlayLeg.game).selectinload(Game.away_team),
        selectinload(Parlay.game_legs).selectinload(ParlayGameLeg.game).selectinload(Game.home_team),
        selectinload(Parlay.game_legs).selectinload(ParlayGameLeg.game).selectinload(Game.away_team),
        selectinload(Parlay.wager),
    )


def parlay_read_with_leg_display(session: Session, parlay: Parlay) -> ParlayRead:
    """Sorted legs with `outcome` + optional `player_full_name` when relationships are loaded."""
    stat_rows = session.scalars(
        select(PlayerGameStat).where(
            PlayerGameStat.game_id.is_not(None),
            PlayerGameStat.game_id.in_([lg.game_id for lg in parlay.legs if lg.game_id is not None]),
            PlayerGameStat.player_id.in_([lg.player_id for lg in parlay.legs]),
        )
    ).all()
    stat_by_leg_key = {(s.player_id, s.game_id): s for s in stat_rows}

    def _leg_stat_value(leg: ParlayLeg) -> float | None:
        if leg.game_id is None:
            return None
        row = stat_by_leg_key.get((leg.player_id, leg.game_id))
        if row is None:
            return None
        if leg.stat_type == StatType.PTS:
            return float(row.points)
        if leg.stat_type == StatType.REB:
            return float(row.rebounds)
        return float(row.assists)

    legs_sorted = sorted(parlay.legs, key=lambda lg: lg.sort_order)
    enriched: list[ParlayLegRead] = []
    for leg in legs_sorted:
        oc = leg_ui_outcome(session, leg)
        pname = leg.player.full_name if leg.player is not None else None
        if leg.game is not None and leg.game.home_team is not None and leg.game.away_team is not None:
            glabel = f"{leg.game.away_team.name} @ {leg.game.home_team.name}"
        elif leg.game_id is not None:
            glabel = f"Game #{leg.game_id}"
        else:
            glabel = None
        row = ParlayLegRead.model_validate(leg).model_copy(
            update={
                "outcome": oc,
                "player_full_name": pname,
                "player_nba_id": leg.player.nba_player_id if leg.player is not None else None,
                "player_team_nba_id": leg.player.team.nba_team_id
                if leg.player is not None and leg.player.team is not None
                else None,
                "game_label": glabel,
                "game_home_team_name": leg.game.home_team.name
                if leg.game is not None and leg.game.home_team is not None
                else None,
                "game_away_team_name": leg.game.away_team.name
                if leg.game is not None and leg.game.away_team is not None
                else None,
                "game_home_score": leg.game.home_score if leg.game is not None else None,
                "game_away_score": leg.game.away_score if leg.game is not None else None,
                "game_date": leg.game.game_date if leg.game is not None else None,
                "game_time_utc": leg.game.game_time_utc if leg.game is not None else None,
                "game_status": leg.game.status if leg.game is not None else None,
                "stat_value": _leg_stat_value(leg),
            },
        )
        enriched.append(row)

    base = ParlayRead.model_validate(parlay)
    game_legs_sorted = sorted(parlay.game_legs, key=lambda lg: lg.sort_order)
    game_enriched: list[ParlayGameLegRead] = []
    for leg in game_legs_sorted:
        oc = game_leg_ui_outcome(session, leg)
        if leg.game is not None and leg.game.home_team is not None and leg.game.away_team is not None:
            glabel = f"{leg.game.away_team.name} @ {leg.game.home_team.name}"
            home = leg.game.home_team.name
            away = leg.game.away_team.name
        else:
            glabel = f"Game #{leg.game_id}"
            home = None
            away = None
        row = ParlayGameLegRead.model_validate(leg).model_copy(
            update={
                "outcome": oc,
                "game_label": glabel,
                "home_team_name": home,
                "away_team_name": away,
                "home_team_nba_id": leg.game.home_team.nba_team_id
                if leg.game is not None and leg.game.home_team is not None
                else None,
                "away_team_nba_id": leg.game.away_team.nba_team_id
                if leg.game is not None and leg.game.away_team is not None
                else None,
                "home_score": leg.game.home_score if leg.game is not None else None,
                "away_score": leg.game.away_score if leg.game is not None else None,
                "game_date": leg.game.game_date if leg.game is not None else None,
                "game_time_utc": leg.game.game_time_utc if leg.game is not None else None,
                "game_status": leg.game.status if leg.game is not None else None,
            }
        )
        game_enriched.append(row)
    stake_cents = parlay.wager.stake_cents if parlay.wager is not None else None
    payout_cents = None
    if parlay.wager is not None:
        if parlay.wager.status in (WagerStatus.WON, WagerStatus.OPEN):
            payout_cents = parlay.wager.potential_return_cents
        else:
            payout_cents = 0
    return base.model_copy(
        update={
            "legs": enriched,
            "game_legs": game_enriched,
            "stake_cents": stake_cents,
            "payout_cents": payout_cents,
        }
    )
