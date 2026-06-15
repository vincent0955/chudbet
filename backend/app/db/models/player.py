from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import Sport

if TYPE_CHECKING:
    from app.db.models.parlay_leg import ParlayLeg
    from app.db.models.player_game_stats import PlayerGameStat
    from app.db.models.team import Team


class Player(Base):
    __tablename__ = "players"

    __table_args__ = (
        Index(
            "uq_players_nba_id",
            "nba_player_id",
            unique=True,
            postgresql_where=text("nba_player_id IS NOT NULL"),
        ),
        Index(
            "uq_players_mlb_id",
            "mlb_player_id",
            unique=True,
            postgresql_where=text("mlb_player_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(sport = 'NBA' AND nba_player_id IS NOT NULL AND mlb_player_id IS NULL) "
            "OR (sport = 'MLB' AND mlb_player_id IS NOT NULL AND nba_player_id IS NULL)",
            name="ck_players_sport_native_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    sport: Mapped[Sport] = mapped_column(
        SQLEnum(Sport, name="sport", native_enum=False, length=8),
        nullable=False,
        server_default=Sport.NBA.value,
    )
    nba_player_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    mlb_player_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    primary_position: Mapped[str | None] = mapped_column(String(32), nullable=True)

    team: Mapped["Team"] = relationship(back_populates="players")
    game_stats: Mapped[list["PlayerGameStat"]] = relationship(back_populates="player")
    parlay_legs: Mapped[list["ParlayLeg"]] = relationship(back_populates="player")
