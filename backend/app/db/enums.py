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
