from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MLBPlayerGameStat(Base):
    __tablename__ = "mlb_player_game_stats"

    __table_args__ = (
        UniqueConstraint("player_id", "game_id", name="uq_mlb_player_game_stat"),
        CheckConstraint("hits >= 0", name="ck_mlb_player_game_stat_hits_nonneg"),
        CheckConstraint("total_bases >= 0", name="ck_mlb_player_game_stat_total_bases_nonneg"),
        CheckConstraint("rbi >= 0", name="ck_mlb_player_game_stat_rbi_nonneg"),
        CheckConstraint("runs >= 0", name="ck_mlb_player_game_stat_runs_nonneg"),
        CheckConstraint(
            "strikeouts_pitcher >= 0",
            name="ck_mlb_player_game_stat_strikeouts_pitcher_nonneg",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id"),
        nullable=False,
        index=True,
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id"),
        nullable=False,
        index=True,
    )
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rbi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strikeouts_pitcher: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
