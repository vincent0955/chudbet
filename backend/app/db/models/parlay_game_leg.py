from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import GameMarketType, GameSelection

if TYPE_CHECKING:
    from app.db.models.game import Game
    from app.db.models.parlay import Parlay


class ParlayGameLeg(Base):
    """One game-market leg: moneyline/spread/total against a game."""

    __tablename__ = "parlay_game_legs"
    __table_args__ = (
        UniqueConstraint("parlay_id", "sort_order", name="uq_parlay_game_leg_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parlay_id: Mapped[int] = mapped_column(
        ForeignKey("parlays.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id"),
        nullable=False,
        index=True,
    )
    market_type: Mapped[GameMarketType] = mapped_column(
        SQLEnum(GameMarketType, name="game_market_type", native_enum=False, length=16),
        nullable=False,
    )
    selection: Mapped[GameSelection] = mapped_column(
        SQLEnum(GameSelection, name="game_selection", native_enum=False, length=16),
        nullable=False,
    )
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds_american: Mapped[int] = mapped_column(Integer, nullable=False)
    leg_probability: Mapped[float] = mapped_column(Float, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )

    parlay: Mapped["Parlay"] = relationship("Parlay", back_populates="game_legs")
    game: Mapped["Game"] = relationship("Game")

