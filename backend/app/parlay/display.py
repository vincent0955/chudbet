"""Build API parlay payloads with per-leg display fields (outcomes, names)."""

from __future__ import annotations

from sqlalchemy.orm import Session, selectinload

from app.api.parlay_schemas import ParlayGameLegRead, ParlayLegRead, ParlayRead
from app.db.models import Game, Parlay, ParlayGameLeg, ParlayLeg
from app.db.enums import WagerStatus
from app.services.settlement import game_leg_ui_outcome, leg_ui_outcome


def parlay_detail_load_options():
    """ORM loader tuple for parlays returned to clients with leg display."""
    return (
        selectinload(Parlay.legs).selectinload(ParlayLeg.player),
        selectinload(Parlay.legs).selectinload(ParlayLeg.game).selectinload(Game.home_team),
        selectinload(Parlay.legs).selectinload(ParlayLeg.game).selectinload(Game.away_team),
        selectinload(Parlay.game_legs).selectinload(ParlayGameLeg.game).selectinload(Game.home_team),
        selectinload(Parlay.game_legs).selectinload(ParlayGameLeg.game).selectinload(Game.away_team),
        selectinload(Parlay.wager),
    )


def parlay_read_with_leg_display(session: Session, parlay: Parlay) -> ParlayRead:
    """Sorted legs with `outcome` + optional `player_full_name` when relationships are loaded."""
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
                "game_label": glabel,
                "game_date": leg.game.game_date if leg.game is not None else None,
                "game_time_utc": leg.game.game_time_utc if leg.game is not None else None,
                "game_status": leg.game.status if leg.game is not None else None,
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
