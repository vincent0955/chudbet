"""Grade open wagers against final box scores (standard and X-of-Y parlays)."""

from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.enums import LegDirection, ParlayMode, StatType, WagerStatus
from app.db.models import Game, Parlay, ParlayLeg, PlayerGameStat, Wager
from app.services import money

logger = logging.getLogger(__name__)

Outcome = Literal["pending", "void", "win", "loss"]


def _is_final_status(status: str | None) -> bool:
    if not status:
        return False
    return "final" in status.lower()


def _stat_value(row: PlayerGameStat, st: StatType) -> int:
    if st == StatType.PTS:
        return row.points
    if st == StatType.REB:
        return row.rebounds
    return row.assists


def _leg_stat_hit(value: float, line: float, direction: LegDirection) -> bool:
    if direction == LegDirection.OVER:
        return value > line
    return value < line


LegUiOutcome = Literal["pending", "hit", "miss", "void"]


def leg_ui_outcome(session: Session, leg: ParlayLeg) -> LegUiOutcome:
    """How to display one leg on the parlay page (matches settlement grading rules)."""
    r = _evaluate_leg(session, leg)
    return {"pending": "pending", "void": "void", "win": "hit", "loss": "miss"}[r]


def _evaluate_leg(session: Session, leg: ParlayLeg) -> Literal["win", "loss", "void", "pending"]:
    if leg.game_id is None:
        return "void"
    game = session.get(Game, leg.game_id)
    if game is None:
        return "void"
    if not _is_final_status(game.status):
        return "pending"
    row = session.scalar(
        select(PlayerGameStat).where(
            PlayerGameStat.player_id == leg.player_id,
            PlayerGameStat.game_id == leg.game_id,
        )
    )
    if row is None:
        return "void"
    val = float(_stat_value(row, leg.stat_type))
    return "win" if _leg_stat_hit(val, float(leg.line), leg.direction) else "loss"


def _resolve_ticket(parlay: Parlay, leg_results: list[str]) -> Outcome:
    if not leg_results:
        return "void"
    if any(r == "pending" for r in leg_results):
        return "pending"
    if any(r == "void" for r in leg_results):
        return "void"

    wins = sum(1 for r in leg_results if r == "win")
    losses = sum(1 for r in leg_results if r == "loss")
    n = len(leg_results)

    if parlay.mode == ParlayMode.X_OF_Y:
        k = parlay.k_required
        if k is None:
            return "void"
        if parlay.wager_on_hit:
            if wins >= k:
                return "win"
            return "loss"
        # Anti X-of-Y not supported for settlement — void to avoid incorrect payouts
        logger.warning("Voiding parlay %s: anti X-of-Y not implemented", parlay.id)
        return "void"

    # Standard parlay
    if parlay.wager_on_hit:
        if losses > 0:
            return "loss"
        return "win"
    # Anti (bet against the parlay hitting)
    if losses > 0:
        return "win"
    return "loss"


def settle_open_wagers(session: Session) -> dict[str, int]:
    """
    Evaluate all OPEN wagers. Commits are left to the caller.

    Returns counters for observability.
    """
    counts: dict[str, int] = {
        "open_seen": 0,
        "pending": 0,
        "won": 0,
        "lost": 0,
        "void": 0,
        "errors": 0,
    }

    wagers = session.scalars(
        select(Wager)
        .where(Wager.status == WagerStatus.OPEN)
        .options(selectinload(Wager.parlay).selectinload(Parlay.legs)),
    ).all()

    for wager in wagers:
        counts["open_seen"] += 1
        parlay = wager.parlay
        if parlay is None:
            counts["errors"] += 1
            logger.error("Wager %s has no parlay row", wager.id)
            continue

        legs = sorted(parlay.legs, key=lambda x: x.sort_order)
        try:
            leg_results = [_evaluate_leg(session, lg) for lg in legs]
            outcome = _resolve_ticket(parlay, leg_results)
            if outcome == "pending":
                counts["pending"] += 1
                continue
            if outcome == "void":
                money.settle_wager_void(session, wager)
                counts["void"] += 1
                logger.info("Wager %s void", wager.id)
                continue
            if outcome == "win":
                money.settle_wager_win(session, wager)
                counts["won"] += 1
                logger.info("Wager %s won", wager.id)
            else:
                money.settle_wager_loss(session, wager)
                counts["lost"] += 1
                logger.info("Wager %s lost", wager.id)
        except Exception:
            counts["errors"] += 1
            logger.exception("Settlement failed for wager %s", wager.id)

    return counts
