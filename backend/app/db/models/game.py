from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.parlay_leg import ParlayLeg
    from app.db.models.player_game_stats import PlayerGameStat
    from app.db.models.team import Team


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    nba_game_id: Mapped[str] = mapped_column(
        String(16),
        unique=True,
        nullable=False,
        index=True,
    )

    home_team: Mapped["Team"] = relationship(
        foreign_keys=[home_team_id],
        back_populates="home_games",
    )
    away_team: Mapped["Team"] = relationship(
        foreign_keys=[away_team_id],
        back_populates="away_games",
    )
    player_stats: Mapped[list["PlayerGameStat"]] = relationship(back_populates="game")
    parlay_legs: Mapped[list["ParlayLeg"]] = relationship(back_populates="game")
