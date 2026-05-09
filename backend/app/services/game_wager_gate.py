"""Rules for whether new wagers may reference a slate game (pre-tip only)."""

from __future__ import annotations

import re

from app.db.models import Game

_ORDINAL_QTR = re.compile(r"\b(?:1ST|2ND|3RD|4TH)\s+QTR\b", re.IGNORECASE)
_SHORT_QTR = re.compile(r"\bQ\s*[1-4]\b", re.IGNORECASE)


def status_indicates_live_or_finished(status: str | None) -> bool:
    """True when NBA ``gameStatusText`` implies tip-off occurred or game is settled (not wagerable).

    Kept aligned with ``UpcomingGames`` live detection on the frontend.
    """
    s = (status or "").strip().upper()
    if not s:
        return False
    if any(x in s for x in ("FINAL", "POSTPONED", "CANCELLED")):
        return True
    if "HALFTIME" in s or "HALF" in s or "END OF" in s:
        return True
    if _SHORT_QTR.search(s) or _ORDINAL_QTR.search(s):
        return True
    if re.search(r"\bOT\b", s):
        return True
    # Game clock fragments from stats feeds without AM/PM/ET (e.g. rolling clock)
    if re.match(r"^\d{1,2}:\d{2}\b", s) and "AM" not in s and "PM" not in s and "ET" not in s:
        return True
    return False


def game_accepts_pre_game_wagers(game: Game | None) -> bool:
    """Allow new slips only before any live/quarter/overtime/halftime terminal state."""
    if game is None:
        return True
    return not status_indicates_live_or_finished(game.status)


def require_pre_game_game_for_wager(game: Game) -> None:
    """Raise ``ValueError`` when the slate row is already in progress or over."""
    if game_accepts_pre_game_wagers(game):
        return
    raise ValueError("This game has already started or finished; wagering is closed for it.")
