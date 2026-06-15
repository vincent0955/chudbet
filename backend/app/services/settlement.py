"""Grade open wagers against final box scores (standard and X-of-Y parlays)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.enums import (
    GameMarketType,
    GameSelection,
    LegDirection,
    ParlayMode,
    Sport,
    StatType,
    WagerStatus,
)
from app.db.models import (
    Game,
    MLBPlayerGameStat,
    Parlay,
    ParlayGameLeg,
    ParlayLeg,
    PlayerGameStat,
    Wager,
)
from app.mlb.enums import MLBStatType
from app.services import money

logger = logging.getLogger(__name__)

Outcome = Literal["pending", "void", "win", "loss"]


def _is_final_status(status: str | None) -> bool:
    """True when NBA ``gameStatusText`` indicates the game is finished (not live)."""
    if not status:
        return False
    s = status.strip().lower()
    if "final" in s or "game over" in s:
        return True
    # Rare shorthand feeds
    if s.startswith("f/") or s.startswith("f "):
        return True
    return False


def _is_game_gradeable(game: Game) -> bool:
    """Legs and tickets stay pending until the game is decisively over."""
    return _is_final_status(game.status)


class StatReader(Protocol):
    """Resolve the reported value of a player-prop stat for a settled game.

    Returns ``None`` when the value is not yet available (no stat row persisted),
    which the caller treats as ``pending`` (Req 14.7).
    """

    def value(
        self, session: Session, player_id: int, game_id: int, stat_type: str
    ) -> int | None: ...


class NbaStatReader:
    """Read NBA player stats from ``PlayerGameStat`` (unchanged NBA path)."""

    def value(
        self, session: Session, player_id: int, game_id: int, stat_type: str
    ) -> int | None:
        row = session.scalar(
            select(PlayerGameStat).where(
                PlayerGameStat.player_id == player_id,
                PlayerGameStat.game_id == game_id,
            )
        )
        if row is None:
            return None
        st = StatType(stat_type)
        if st == StatType.PTS:
            return row.points
        if st == StatType.REB:
            return row.rebounds
        return row.assists


# Map each MLB stat vocabulary member to its ``MLBPlayerGameStat`` column.
_MLB_STAT_COLUMNS: dict[MLBStatType, str] = {
    MLBStatType.HITS: "hits",
    MLBStatType.TOTAL_BASES: "total_bases",
    MLBStatType.RBI: "rbi",
    MLBStatType.RUNS: "runs",
    MLBStatType.STRIKEOUTS_PITCHER: "strikeouts_pitcher",
}


class MlbStatReader:
    """Read MLB player stats from ``MLBPlayerGameStat`` by ``MLBStatType``."""

    def value(
        self, session: Session, player_id: int, game_id: int, stat_type: str
    ) -> int | None:
        row = session.scalar(
            select(MLBPlayerGameStat).where(
                MLBPlayerGameStat.player_id == player_id,
                MLBPlayerGameStat.game_id == game_id,
            )
        )
        if row is None:
            return None
        return getattr(row, _MLB_STAT_COLUMNS[MLBStatType(stat_type)])


STAT_READERS: dict[Sport, StatReader] = {
    Sport.NBA: NbaStatReader(),
    Sport.MLB: MlbStatReader(),
}


def _leg_stat_hit(value: float, line: float, direction: LegDirection) -> bool:
    if direction == LegDirection.OVER:
        return value > line
    return value < line


LegUiOutcome = Literal["pending", "hit", "miss", "void"]


def _ui_from_eval_result(r: Literal["win", "loss", "void", "pending"]) -> LegUiOutcome:
    return {"pending": "pending", "void": "void", "win": "hit", "loss": "miss"}[r]


def _normalize_persisted_outcome(value: str | None) -> LegUiOutcome | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("pending", "hit", "miss", "void"):
        return v  # type: ignore[return-value]
    return None


def _parlay_has_open_wager(session: Session, parlay_id: int) -> bool:
    return (
        session.scalar(
            select(Wager.id)
            .where(Wager.parlay_id == parlay_id, Wager.status == WagerStatus.OPEN)
            .limit(1)
        )
        is not None
    )


def leg_ui_outcome(session: Session, leg: ParlayLeg) -> LegUiOutcome:
    """How to display one leg on the parlay page."""
    if not _parlay_has_open_wager(session, leg.parlay_id):
        persisted = _normalize_persisted_outcome(getattr(leg, "outcome_status", None))
        if persisted is not None:
            return persisted
    return _ui_from_eval_result(_evaluate_leg(session, leg))


def _evaluate_leg(session: Session, leg: ParlayLeg) -> Literal["win", "loss", "void", "pending"]:
    if leg.game_id is None:
        return "void"
    game = session.get(Game, leg.game_id)
    if game is None:
        return "void"
    if not _is_game_gradeable(game):
        return "pending"
    reader = STAT_READERS[game.sport]
    val = reader.value(session, leg.player_id, leg.game_id, leg.stat_type)
    if val is None:
        return "pending"
    return "win" if _leg_stat_hit(float(val), float(leg.line), leg.direction) else "loss"


def game_leg_ui_outcome(session: Session, leg: ParlayGameLeg) -> LegUiOutcome:
    if not _parlay_has_open_wager(session, leg.parlay_id):
        persisted = _normalize_persisted_outcome(getattr(leg, "outcome_status", None))
        if persisted is not None:
            return persisted
    return _ui_from_eval_result(_evaluate_game_leg(session, leg))


def _evaluate_game_leg(session: Session, leg: ParlayGameLeg) -> Literal["win", "loss", "void", "pending"]:
    game = session.get(Game, leg.game_id)
    if game is None:
        return "void"
    if not _is_game_gradeable(game):
        return "pending"
    if game.home_score is None or game.away_score is None:
        return "pending"

    home = float(game.home_score)
    away = float(game.away_score)
    if leg.market_type == GameMarketType.MONEYLINE:
        if home == away:
            return "void"
        if leg.selection == GameSelection.HOME:
            return "win" if home > away else "loss"
        if leg.selection == GameSelection.AWAY:
            return "win" if away > home else "loss"
        return "void"

    if leg.line is None:
        return "void"

    if leg.market_type == GameMarketType.SPREAD:
        margin = home - away
        adjusted = margin + float(leg.line) if leg.selection == GameSelection.HOME else (-margin) + float(leg.line)
        if adjusted == 0:
            return "void"
        return "win" if adjusted > 0 else "loss"

    total = home + away
    diff = total - float(leg.line)
    if diff == 0:
        return "void"
    if leg.selection == GameSelection.OVER:
        return "win" if diff > 0 else "loss"
    if leg.selection == GameSelection.UNDER:
        return "win" if diff < 0 else "loss"
    return "void"


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


def _ticket_game_sports(session: Session, wager: Wager) -> set[Sport]:
    """Sports referenced by a wager's player-prop and game legs."""
    parlay = wager.parlay
    if parlay is None:
        return set()

    game_ids = {lg.game_id for lg in parlay.legs if lg.game_id is not None}
    game_ids |= {gl.game_id for gl in parlay.game_legs if gl.game_id is not None}
    if not game_ids:
        return set()

    sports = session.scalars(select(Game.sport).where(Game.id.in_(game_ids))).all()
    return set(sports)


def ticket_contains_mlb_leg(session: Session, wager: Wager) -> bool:
    """True when any leg references an MLB game (Req 7.7, 15.1)."""
    return Sport.MLB in _ticket_game_sports(session, wager)


def ticket_is_pure_nba(session: Session, wager: Wager) -> bool:
    """True when the ticket has no MLB legs (NBA worker scope)."""
    return Sport.MLB not in _ticket_game_sports(session, wager)


def settle_open_wagers(
    session: Session,
    *,
    sport_scope: Callable[[Session, Wager], bool] | None = None,
) -> dict[str, int]:
    """
    Evaluate OPEN wagers, optionally filtered by ``sport_scope``.

    When ``sport_scope`` is provided, only wagers for which the predicate
    returns ``True`` are graded. The NBA worker passes
    :func:`ticket_is_pure_nba`; the MLB worker passes
    :func:`ticket_contains_mlb_leg` (Req 7.7, 15.1).

    Commits are left to the caller. Returns counters for observability.
    """
    counts: dict[str, int] = {
        "open_seen": 0,
        "pending": 0,
        "won": 0,
        "lost": 0,
        "void": 0,
        "errors": 0,
        "skipped_scope": 0,
    }

    wagers = session.scalars(
        select(Wager)
        .where(Wager.status == WagerStatus.OPEN)
        .options(
            selectinload(Wager.parlay).selectinload(Parlay.legs),
            selectinload(Wager.parlay).selectinload(Parlay.game_legs),
        ),
    ).all()

    for wager in wagers:
        counts["open_seen"] += 1
        if sport_scope is not None and not sport_scope(session, wager):
            counts["skipped_scope"] += 1
            continue
        parlay = wager.parlay
        if parlay is None:
            counts["errors"] += 1
            logger.error("Wager %s has no parlay row", wager.id)
            continue

        legs = sorted(parlay.legs, key=lambda x: x.sort_order)
        game_legs = sorted(parlay.game_legs, key=lambda x: x.sort_order)
        try:
            leg_eval_results = [_evaluate_leg(session, lg) for lg in legs]
            game_leg_eval_results = [_evaluate_game_leg(session, gl) for gl in game_legs]
            for lg, ev in zip(legs, leg_eval_results, strict=False):
                lg.outcome_status = _ui_from_eval_result(ev)
            for gl, ev in zip(game_legs, game_leg_eval_results, strict=False):
                gl.outcome_status = _ui_from_eval_result(ev)
            leg_results = leg_eval_results + game_leg_eval_results
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
