from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import LegDirection

if TYPE_CHECKING:
    from app.db.models.game import Game
    from app.db.models.parlay import Parlay
    from app.db.models.player import Player


class ParlayLeg(Base):
    """One leg of a parlay: player stat vs line (optionally tied to a specific game)."""

    __tablename__ = "parlay_legs"
    __table_args__ = (
        UniqueConstraint("parlay_id", "sort_order", name="uq_parlay_leg_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parlay_id: Mapped[int] = mapped_column(
        ForeignKey("parlays.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id"),
        nullable=False,
        index=True,
    )
    game_id: Mapped[int | None] = mapped_column(
        ForeignKey("games.id"),
        nullable=True,
        index=True,
    )
    stat_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    line: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[LegDirection] = mapped_column(
        SQLEnum(LegDirection, name="parlay_leg_direction", native_enum=False, length=16),
        nullable=False,
    )
    leg_probability: Mapped[float] = mapped_column(Float, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )

    parlay: Mapped["Parlay"] = relationship("Parlay", back_populates="legs")
    player: Mapped["Player"] = relationship("Player", back_populates="parlay_legs")
    game: Mapped["Game | None"] = relationship("Game", back_populates="parlay_legs")
