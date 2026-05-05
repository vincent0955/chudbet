from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.game import Game
    from app.db.models.player import Player


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    nba_team_id: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        nullable=False,
        index=True,
    )

    players: Mapped[list["Player"]] = relationship(back_populates="team")
    home_games: Mapped[list["Game"]] = relationship(
        "Game",
        foreign_keys="Game.home_team_id",
        back_populates="home_team",
    )
    away_games: Mapped[list["Game"]] = relationship(
        "Game",
        foreign_keys="Game.away_team_id",
        back_populates="away_team",
    )
