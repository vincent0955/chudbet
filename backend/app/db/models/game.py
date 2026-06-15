from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import Sport

if TYPE_CHECKING:
    from app.db.models.parlay_leg import ParlayLeg
    from app.db.models.player_game_stats import PlayerGameStat
    from app.db.models.team import Team


class Game(Base):
    __tablename__ = "games"

    __table_args__ = (
        Index(
            "uq_games_nba_id",
            "nba_game_id",
            unique=True,
            postgresql_where=text("nba_game_id IS NOT NULL"),
        ),
        Index(
            "uq_games_mlb_id",
            "mlb_game_id",
            unique=True,
            postgresql_where=text("mlb_game_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(sport = 'NBA' AND nba_game_id IS NOT NULL AND mlb_game_id IS NULL) "
            "OR (sport = 'MLB' AND mlb_game_id IS NOT NULL AND nba_game_id IS NULL)",
            name="ck_games_sport_native_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    game_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    sport: Mapped[Sport] = mapped_column(
        SQLEnum(Sport, name="sport", native_enum=False, length=8),
        nullable=False,
        server_default=Sport.NBA.value,
    )
    nba_game_id: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        index=True,
    )
    mlb_game_id: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
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
