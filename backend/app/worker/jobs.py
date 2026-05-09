"""Scheduled jobs: NBA ingest + wager settlement."""

from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db import models  # noqa: F401 — register models
from app.db.migrate import ensure_postgres_schema
from app.db.session import get_engine
from app.ingestion.nba_sync import run_full_ingest
from app.services.settlement import settle_open_wagers

logger = logging.getLogger(__name__)


def _truthy(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes")


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def run_ingest_job() -> None:
    """Pull recent slate / box scores using env-tuned `run_full_ingest`."""
    logger.info("Ingest job starting")
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    ensure_postgres_schema(engine)

    season = os.getenv("NBA_SEASON", "2025-26")
    scoreboard_days = _int_env("WORKER_SCOREBOARD_DAYS", 3)
    scoreboard_past_days = _int_env("WORKER_SCOREBOARD_PAST_DAYS", 0)
    max_games_raw = os.getenv("WORKER_MAX_GAMES", "").strip()
    max_games = int(max_games_raw) if max_games_raw.isdigit() else None

    with Session(engine) as session:
        run_full_ingest(
            session,
            season=season,
            regular_only=True,
            max_games=max_games,
            recent_first=_truthy("WORKER_RECENT_FIRST", "true"),
            scoreboard_days=scoreboard_days,
            scoreboard_past_days=scoreboard_past_days,
            skip_rosters=_truthy("WORKER_SKIP_ROSTERS", "true"),
            skip_games=_truthy("WORKER_SKIP_GAMES", "true"),
            skip_stats=False,
        )
    logger.info("Ingest job finished")


def run_settlement_job() -> None:
    """Grade OPEN wagers against DB box scores."""
    logger.info("Settlement job starting")
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    ensure_postgres_schema(engine)

    with Session(engine) as session:
        summary = settle_open_wagers(session)
        session.commit()
    logger.info("Settlement job finished: %s", summary)
