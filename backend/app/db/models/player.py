from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.parlay_leg import ParlayLeg
    from app.db.models.player_game_stats import PlayerGameStat
    from app.db.models.team import Team


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    nba_player_id: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        nullable=False,
        index=True,
    )

    team: Mapped["Team"] = relationship(back_populates="players")
    game_stats: Mapped[list["PlayerGameStat"]] = relationship(back_populates="player")
    parlay_legs: Mapped[list["ParlayLeg"]] = relationship(back_populates="player")
