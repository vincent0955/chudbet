from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Index, Integer, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import Sport

if TYPE_CHECKING:
    from app.db.models.game import Game
    from app.db.models.player import Player


class Team(Base):
    __tablename__ = "teams"

    __table_args__ = (
        Index(
            "uq_teams_nba_id",
            "nba_team_id",
            unique=True,
            postgresql_where=text("nba_team_id IS NOT NULL"),
        ),
        Index(
            "uq_teams_mlb_id",
            "mlb_team_id",
            unique=True,
            postgresql_where=text("mlb_team_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(sport = 'NBA' AND nba_team_id IS NOT NULL AND mlb_team_id IS NULL) "
            "OR (sport = 'MLB' AND mlb_team_id IS NOT NULL AND nba_team_id IS NULL)",
            name="ck_teams_sport_native_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sport: Mapped[Sport] = mapped_column(
        SQLEnum(Sport, name="sport", native_enum=False, length=8),
        nullable=False,
        server_default=Sport.NBA.value,
    )
    nba_team_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    mlb_team_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    abbreviation: Mapped[str | None] = mapped_column(String(16), nullable=True)

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
