"""Build API parlay payloads with per-leg display fields (outcomes, names)."""

from __future__ import annotations

from sqlalchemy.orm import Session, selectinload

from app.api.parlay_schemas import ParlayLegRead, ParlayRead
from app.db.models import Parlay, ParlayLeg
from app.services.settlement import leg_ui_outcome


def parlay_detail_load_options():
    """ORM loader tuple for parlays returned to clients with leg display."""
    return (
        selectinload(Parlay.legs).selectinload(ParlayLeg.player),
        selectinload(Parlay.legs).selectinload(ParlayLeg.game),
    )


def parlay_read_with_leg_display(session: Session, parlay: Parlay) -> ParlayRead:
    """Sorted legs with `outcome` + optional `player_full_name` when relationships are loaded."""
    legs_sorted = sorted(parlay.legs, key=lambda lg: lg.sort_order)
    enriched: list[ParlayLegRead] = []
    for leg in legs_sorted:
        oc = leg_ui_outcome(session, leg)
        pname = leg.player.full_name if leg.player is not None else None
        row = ParlayLegRead.model_validate(leg).model_copy(
            update={"outcome": oc, "player_full_name": pname},
        )
        enriched.append(row)

    base = ParlayRead.model_validate(parlay)
    return base.model_copy(update={"legs": enriched})
