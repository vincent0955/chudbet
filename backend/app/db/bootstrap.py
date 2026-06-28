"""Safe database preparation for API startup and background workers.

Multiple processes (API + NBA worker + MLB worker) can start concurrently against
the same Postgres database. ``Base.metadata.create_all`` is not concurrency-safe
on Postgres when enum/composite types are involved and can raise::

    duplicate key value violates unique constraint "pg_type_typname_nsp_index"

A session-level advisory lock serializes schema bootstrap. ``pg_try_advisory_lock``
with short retries avoids blocking API startup when a worker is already migrating.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.base import Base
from app.db.migrate import ensure_postgres_schema

logger = logging.getLogger(__name__)

_SCHEMA_BOOTSTRAP_LOCK_ID = 8_424_242
_LOCK_ATTEMPTS = 120  # 120 * 0.25s = 30s max wait
_LOCK_SLEEP_SEC = 0.25


def _is_deadlock(exc: BaseException) -> bool:
    return "deadlock" in str(exc).lower()


def _bootstrap_schema(engine: Engine) -> None:
    try:
        Base.metadata.create_all(bind=engine)
    except IntegrityError as exc:
        logger.warning("create_all hit a concurrent DDL race (continuing): %s", exc)
    ensure_postgres_schema(engine)


def prepare_worker_engine(engine: Engine) -> None:
    """Lightweight preparation for background workers (migrations only).

    Workers must not run ``create_all`` on every job tick — that races with the
    API and other workers and can hold the bootstrap lock for tens of seconds.
    Tables are created by the API (or the first full bootstrap) instead.
    """
    ensure_postgres_schema(engine)


def prepare_database_engine(engine: Engine) -> None:
    """Create tables (if needed) and apply additive migrations."""
    if engine.dialect.name != "postgresql":
        _bootstrap_schema(engine)
        return

    for attempt in range(_LOCK_ATTEMPTS):
        try:
            with engine.connect() as conn:
                locked = conn.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": _SCHEMA_BOOTSTRAP_LOCK_ID},
                ).scalar()
                if not locked:
                    time.sleep(_LOCK_SLEEP_SEC)
                    continue
                try:
                    _bootstrap_schema(engine)
                    return
                finally:
                    conn.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": _SCHEMA_BOOTSTRAP_LOCK_ID},
                    )
        except OperationalError as exc:
            if _is_deadlock(exc) and attempt < _LOCK_ATTEMPTS - 1:
                logger.warning("Schema bootstrap deadlock (retry %s): %s", attempt + 1, exc)
                time.sleep(_LOCK_SLEEP_SEC)
                continue
            raise

    logger.warning(
        "Schema bootstrap lock not acquired after %ss; running migrations only",
        _LOCK_ATTEMPTS * _LOCK_SLEEP_SEC,
    )
    for attempt in range(_LOCK_ATTEMPTS):
        try:
            ensure_postgres_schema(engine)
            return
        except OperationalError as exc:
            if _is_deadlock(exc) and attempt < _LOCK_ATTEMPTS - 1:
                logger.warning("Schema migration deadlock (retry %s): %s", attempt + 1, exc)
                time.sleep(_LOCK_SLEEP_SEC)
                continue
            raise
