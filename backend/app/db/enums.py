"""Shared enum types stored as VARCHAR via SQLAlchemy (native_enum=False)."""

from enum import StrEnum


class ParlayMode(StrEnum):
    STANDARD = "standard"
    X_OF_Y = "x_of_y"


class StatType(StrEnum):
    PTS = "PTS"
    REB = "REB"
    AST = "AST"


class LegDirection(StrEnum):
    OVER = "OVER"
    UNDER = "UNDER"


class GameMarketType(StrEnum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"


class GameSelection(StrEnum):
    HOME = "home"
    AWAY = "away"
    OVER = "over"
    UNDER = "under"


class LedgerEntryType(StrEnum):
    DEPOSIT = "deposit"
    WAGER_STAKE = "wager_stake"
    WAGER_PAYOUT = "wager_payout"
    WAGER_VOID = "wager_void"
    ADJUSTMENT = "adjustment"


class WagerStatus(StrEnum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"
    VOID = "void"
    CANCELLED = "cancelled"
