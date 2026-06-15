"""MLB game status classification (Requirement 4.2).

Maps the MLB Stats API status fields (``abstractGameState`` and ``detailedState``)
into exactly one of three coarse classes used by ingestion, the pre-game wager
gate, and settlement. ``classify_status`` is a *total* function: every possible
input -- including ``None`` and blank strings -- maps to exactly one class.

Classification rules:

- ``Final`` / ``Game Over``                         -> FINAL
- ``Scheduled`` / ``Pre-Game`` / ``Warmup``         -> PRE_GAME
- unknown / blank / ``None``                        -> PRE_GAME
- everything else (``In Progress``, ``Manager
  Challenge``, ``Delayed`` after first pitch, ...)  -> LIVE

Defaulting unknown/blank to PRE_GAME guarantees an unstarted or
unrecognized game is never treated as gradeable.

Note on ``Warmup``: the design distinguishes pre-first-pitch ``Warmup``
(PRE_GAME) from post-first-pitch ``Warmup`` (LIVE), but this function only
receives the two state strings (no first-pitch timestamp). Consistent with the
"unknown defaults to PRE_GAME" rule, ``Warmup`` is classified as PRE_GAME (the
conservative pre-game classification).
"""

from enum import StrEnum


class MLBGameStatus(StrEnum):
    PRE_GAME = "pre_game"
    LIVE = "live"
    FINAL = "final"


# Normalized (lowercased, whitespace-trimmed) detailedState / abstractGameState
# values that classify as FINAL.
_FINAL_STATES: frozenset[str] = frozenset({"final", "game over"})

# Normalized values that classify as PRE_GAME. "warmup" is treated as PRE_GAME
# (the conservative pre-game classification) since no first-pitch timestamp is
# available here. "preview" is the abstractGameState fallback for pre-game.
_PRE_GAME_STATES: frozenset[str] = frozenset(
    {"scheduled", "pre-game", "pregame", "warmup", "preview"}
)


def _normalize(state: str | None) -> str:
    """Lowercase and strip surrounding whitespace; ``None`` becomes ``""``."""
    if state is None:
        return ""
    return state.strip().lower()


def classify_status(
    abstract_state: str | None, detailed_state: str | None
) -> MLBGameStatus:
    """Classify an MLB game's status into exactly one ``MLBGameStatus``.

    ``detailed_state`` is the more specific signal (e.g. "Scheduled",
    "Pre-Game", "Warmup", "In Progress", "Final", "Game Over") and is consulted
    first; ``abstract_state`` (e.g. "Preview", "Live", "Final") is used as a
    fallback. Matching is case-insensitive and tolerant of surrounding
    whitespace. This is a total function: any input maps to exactly one class.
    """
    detailed = _normalize(detailed_state)
    abstract = _normalize(abstract_state)

    # detailedState is most specific -- prefer it when it is a recognized value.
    if detailed in _FINAL_STATES:
        return MLBGameStatus.FINAL
    if detailed in _PRE_GAME_STATES:
        return MLBGameStatus.PRE_GAME

    # Fall back to abstractGameState when detailedState is blank/unrecognized.
    if detailed == "":
        if abstract in _FINAL_STATES:
            return MLBGameStatus.FINAL
        if abstract in _PRE_GAME_STATES:
            return MLBGameStatus.PRE_GAME
        if abstract == "":
            # Both blank/unknown -> conservative PRE_GAME (never gradeable).
            return MLBGameStatus.PRE_GAME
        # A recognized non-pre/non-final abstract state (e.g. "Live").
        return MLBGameStatus.LIVE

    # detailedState is present but not a pre-game/final value -> live
    # (In Progress, Manager Challenge, Delayed after first pitch, etc.).
    return MLBGameStatus.LIVE
