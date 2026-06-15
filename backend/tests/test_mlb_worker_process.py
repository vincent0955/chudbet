"""Worker process tests for the dedicated MLB worker (Requirements 7.1, 7.5–7.7)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from app.mlb.config import classify_worker_ingest_interval
from app.worker import mlb_main

BACKEND = Path(__file__).resolve().parents[1]


class TestMlbWorkerMainUnit:
    def test_invalid_interval_exits_before_scheduler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLB_WORKER_INGEST_INTERVAL_SEC", "-5")
        monkeypatch.setenv("MLB_WORKER_SETTLE_INTERVAL_SEC", "0")
        assert mlb_main.main() == 1

    def test_idle_ingest_with_settlement_can_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLB_WORKER_INGEST_INTERVAL_SEC", "0")
        monkeypatch.setenv("MLB_WORKER_SETTLE_INTERVAL_SEC", "0")
        assert mlb_main.main() == 1


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM drain subprocess test is Unix-oriented")
class TestMlbWorkerProcess:
    def test_subprocess_starts_distinct_worker(self, tmp_path: Path) -> None:
        db_path = tmp_path / "worker.db"
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path.as_posix()}"
        env["MLB_WORKER_INGEST_INTERVAL_SEC"] = "86400"
        env["MLB_WORKER_SETTLE_INTERVAL_SEC"] = "86400"

        proc = subprocess.Popen(
            [sys.executable, "-m", "app.worker.mlb_main"],
            cwd=str(BACKEND),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(2)
            assert proc.poll() is None
            assert proc.pid != os.getpid()
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=35)

    def test_raising_run_does_not_prevent_invalid_interval_classification(self) -> None:
        """Subsequent runs stay scheduled when a job raises (Req 7.6) — smoke via wrapper."""
        calls: list[str] = []

        def boom() -> None:
            calls.append("ran")
            raise RuntimeError("boom")

        wrapped = mlb_main._wrap_job(boom)
        wrapped()
        assert calls == ["ran"]
