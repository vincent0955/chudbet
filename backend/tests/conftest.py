"""Shared pytest fixtures.

Provides an isolated in-memory SQLite database per test so service-layer code
that talks to a real ``Session`` (money, settlement, parlay creation) can be
exercised without Postgres or Docker.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base

# Importing the models package registers every table on ``Base.metadata`` and
# wires up relationships, which ``create_all`` below relies on.
import app.db.models  # noqa: F401


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
