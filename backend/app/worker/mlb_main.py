"""
Dedicated MLB background worker (Requirements 7.1–7.7).

Run:  python -m app.worker.mlb_main

Uses ``BlockingScheduler`` so the main thread stays alive in Docker. Schedules
MLB ingest (when the ingest interval is valid and non-zero) and wager
settlement independently of the NBA worker at ``app.worker.main``.

Environment:
  POSTGRES_*                         — same as API
  MLB_WORKER_INGEST_INTERVAL_SEC     — default 300; 1–86400 schedules ingest;
                                       0 keeps the process alive without ingest;
                                       negative / non-numeric / >86400 logs and exits
  MLB_WORKER_SETTLE_INTERVAL_SEC     — default 300; 0 disables settlement job
  MLB_*                              — Stats API / pricing knobs (see ``app.mlb.config``)
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading

from apscheduler.schedulers.blocking import BlockingScheduler

from app.mlb.config import (
    classify_worker_ingest_interval,
    get_worker_ingest_interval_raw,
    get_worker_settle_interval_sec,
)
from app.worker.mlb_jobs import run_mlb_ingest_job, run_mlb_settlement_job

logger = logging.getLogger(__name__)

_JOB_DRAIN_TIMEOUT_SEC = 30
_in_progress = threading.Event()


def _wrap_job(fn):
    """Track in-progress runs so shutdown can drain gracefully (Req 7.5)."""

    def wrapped() -> None:
        _in_progress.set()
        try:
            fn()
        except Exception:
            logger.exception("%s failed — next run remains scheduled", fn.__name__)
        finally:
            _in_progress.clear()

    wrapped.__name__ = getattr(fn, "__name__", "mlb_job")
    return wrapped


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )

    ingest_raw = get_worker_ingest_interval_raw()
    ingest_class = classify_worker_ingest_interval(ingest_raw)
    settle_sec = get_worker_settle_interval_sec()

    if ingest_class.mode == "invalid":
        logger.error(
            "Invalid MLB_WORKER_INGEST_INTERVAL_SEC=%r — must be 0 or 1–86400",
            ingest_raw,
        )
        return 1

    tz = os.getenv("WORKER_TZ", "UTC").strip() or "UTC"
    sched = BlockingScheduler(timezone=tz)

    if ingest_class.mode == "schedule":
        assert ingest_class.seconds is not None
        sched.add_job(
            _wrap_job(run_mlb_ingest_job),
            "interval",
            seconds=ingest_class.seconds,
            id="mlb_ingest",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.info("Scheduled MLB ingest every %s s", ingest_class.seconds)
    else:
        logger.info("MLB ingest job disabled (MLB_WORKER_INGEST_INTERVAL_SEC=0)")

    if settle_sec > 0:
        sched.add_job(
            _wrap_job(run_mlb_settlement_job),
            "interval",
            seconds=settle_sec,
            id="mlb_settle",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.info("Scheduled MLB settlement every %s s", settle_sec)
    else:
        logger.info("MLB settlement job disabled (MLB_WORKER_SETTLE_INTERVAL_SEC=0)")

    if ingest_class.mode != "schedule" and settle_sec <= 0:
        logger.error(
            "No MLB jobs enabled; set MLB_WORKER_INGEST_INTERVAL_SEC to 1–86400 "
            "and/or MLB_WORKER_SETTLE_INTERVAL_SEC > 0"
        )
        return 1

    shutting_down = False

    def shutdown(signum: int, _frame: object | None) -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        logger.info("Signal %s — shutting down MLB worker", signum)
        try:
            sched.shutdown(wait=False)
        except Exception:
            logger.exception("Scheduler shutdown")
        if _in_progress.is_set():
            logger.info("Waiting up to %s s for in-progress MLB job", _JOB_DRAIN_TIMEOUT_SEC)
            _in_progress.wait(timeout=_JOB_DRAIN_TIMEOUT_SEC)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    if ingest_class.mode == "schedule":
        try:
            _wrap_job(run_mlb_ingest_job)()
        except Exception:
            logger.exception("Initial MLB ingest failed")

    if settle_sec > 0:
        try:
            _wrap_job(run_mlb_settlement_job)()
        except Exception:
            logger.exception("Initial MLB settlement failed")

    logger.info("MLB worker running (BlockingScheduler); stop with SIGTERM/SIGINT")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    if _in_progress.is_set():
        _in_progress.wait(timeout=_JOB_DRAIN_TIMEOUT_SEC)
    logger.info("MLB worker exited")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.basicConfig(level=logging.ERROR, stream=sys.stderr, force=True)
        logging.exception(
            "MLB worker failed before scheduler started — check imports and DATABASE_URL"
        )
        raise SystemExit(1) from None
