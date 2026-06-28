"""Tests for concurrent-safe database bootstrap."""

from __future__ import annotations

from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

import app.db.models  # noqa: F401
from app.db.bootstrap import prepare_database_engine


def test_prepare_database_engine_continues_after_create_all_race(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    calls: list[str] = []

    def boom(*_args, **_kwargs) -> None:
        calls.append("create_all")
        raise IntegrityError("stmt", {}, mock.Mock(orig=Exception("pg_type_typname_nsp_index")))

    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    monkeypatch.setattr(
        "app.db.bootstrap.time.sleep",
        lambda _sec: None,
    )

    lock_state = {"held": False}

    class _Result:
        def scalar(self):
            if not lock_state["held"]:
                lock_state["held"] = True
                return True
            return False

    class _Conn:
        def execute(self, sql, params=None):
            if "pg_try_advisory_lock" in str(sql):
                return _Result()
            if "pg_advisory_unlock" in str(sql):
                lock_state["held"] = False
            return _Result()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(engine, "connect", lambda: _Conn())
    monkeypatch.setattr("app.db.bootstrap.Base.metadata.create_all", boom)
    monkeypatch.setattr(
        "app.db.bootstrap.ensure_postgres_schema",
        lambda _engine: calls.append("migrate"),
    )

    prepare_database_engine(engine)

    assert calls == ["create_all", "migrate"]
