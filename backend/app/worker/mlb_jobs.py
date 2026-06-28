"""Scheduled jobs for the dedicated MLB worker (Requirement 7.6).

This module holds the two jobs the MLB worker process schedules:

- ``run_mlb_ingest_job``     -- runs the full MLB ingestion pipeline.
- ``run_mlb_settlement_job`` -- settles wagers on MLB-containing tickets.

Per the module-boundary rule (Requirements 2.x, 7.6) this worker imports **only**
MLB ingestion (``app.mlb.ingestion``) plus the *shared* settlement service
(``app.services.settlement``). It never imports the NBA worker
(``app.worker.jobs`` / ``app.worker.main``) and the NBA worker never imports
this module; the two worker processes are fully independent (Req 7.1, 7.7).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db import models  # noqa: F401 — register models
from app.db.bootstrap import prepare_worker_engine
from app.db.session import get_engine
from app.mlb.ingestion import run_full_mlb_ingest
from app.mlb.stats_api_client import MLBStatsAPIClient
from app.services.settlement import settle_open_wagers, ticket_contains_mlb_leg

logger = logging.getLogger(__name__)


def _prepare_engine():
    """Ensure the schema exists before a job touches the database."""
    engine = get_engine()
    prepare_worker_engine(engine)
    return engine


def run_mlb_ingest_job() -> None:
    """Pull MLB teams, rosters, schedule, and box scores."""
    logger.info("MLB ingest job starting")
    engine = _prepare_engine()

    client = MLBStatsAPIClient()
    with Session(engine) as session:
        summary = run_full_mlb_ingest(session, client)
        session.commit()
    logger.info("MLB ingest job finished: %s", summary)


def run_mlb_settlement_job() -> None:
    """Grade OPEN wagers on MLB-containing tickets via shared settlement."""
    logger.info("MLB settlement job starting")
    engine = _prepare_engine()

    with Session(engine) as session:
        summary = settle_open_wagers(session, sport_scope=ticket_contains_mlb_leg)
        session.commit()
    logger.info("MLB settlement job finished: %s", summary)
