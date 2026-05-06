"""
Background worker (Option 1): APScheduler runs NBA ingest + wager settlement on intervals.

Run:  python -m app.worker.main

Uses BlockingScheduler so the main thread stays alive (reliable in Docker; BackgroundScheduler
uses daemon threads and some environments exit immediately).

Environment (typical):
  POSTGRES_*           — same as API
  WORKER_INGEST_INTERVAL_SEC   — default 900 (15 min), 0 disables ingest job
  WORKER_SETTLE_INTERVAL_SEC   — default 120 (2 min), 0 disables settlement job
  NBA_SEASON, WORKER_SCOREBOARD_DAYS, WORKER_SKIP_ROSTERS, WORKER_SKIP_GAMES, ...
"""

from __future__ import annotations

import logging
import os
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler

from app.worker.jobs import run_ingest_job, run_settlement_job

logger = logging.getLogger(__name__)


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )

    ingest_sec = _int_env("WORKER_INGEST_INTERVAL_SEC", 900)
    settle_sec = _int_env("WORKER_SETTLE_INTERVAL_SEC", 120)

    tz = os.getenv("WORKER_TZ", "UTC").strip() or "UTC"
    sched = BlockingScheduler(timezone=tz)

    if ingest_sec > 0:
        sched.add_job(
            run_ingest_job,
            "interval",
            seconds=ingest_sec,
            id="nba_ingest",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.info("Scheduled NBA ingest every %s s", ingest_sec)
    else:
        logger.info("NBA ingest job disabled (WORKER_INGEST_INTERVAL_SEC=0)")

    if settle_sec > 0:
        sched.add_job(
            run_settlement_job,
            "interval",
            seconds=settle_sec,
            id="settle_wagers",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.info("Scheduled settlement every %s s", settle_sec)
    else:
        logger.info("Settlement job disabled (WORKER_SETTLE_INTERVAL_SEC=0)")

    if ingest_sec <= 0 and settle_sec <= 0:
        logger.error("No jobs enabled; set interval env vars > 0")
        return 1

    def shutdown(signum: int, _frame: object | None) -> None:
        logger.info("Signal %s — shutting down worker", signum)
        try:
            sched.shutdown(wait=False)
        except Exception:
            logger.exception("Scheduler shutdown")

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Run once before blocking so dev gets immediate feedback / data refresh
    if ingest_sec > 0:
        try:
            run_ingest_job()
        except Exception:
            logger.exception("Initial ingest failed")
    if settle_sec > 0:
        try:
            run_settlement_job()
        except Exception:
            logger.exception("Initial settlement failed")

    logger.info("Worker running (BlockingScheduler); stop with SIGTERM/SIGINT")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    logger.info("Worker exited")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.basicConfig(level=logging.ERROR, stream=sys.stderr, force=True)
        logging.exception("Worker failed before scheduler started — check imports and DATABASE_URL")
        raise SystemExit(1) from None
