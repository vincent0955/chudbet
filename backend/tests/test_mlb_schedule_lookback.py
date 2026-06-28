"""Tests for MLB schedule lookback window."""

from __future__ import annotations

from datetime import date, timedelta

from app.mlb.ingestion import sync_schedule


class _RecordingClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.start: date | None = None
        self.end: date | None = None

    def schedule(self, start: date, end: date) -> list[dict]:
        self.start = start
        self.end = end
        return self.payloads


def test_sync_schedule_requests_lookback_window(session, monkeypatch) -> None:
    """Schedule fetch should include past days for finals/prop samples."""
    from app.db.enums import Sport
    from app.db.models import Team

    monkeypatch.setenv("MLB_SCHEDULE_LOOKBACK_DAYS", "14")
    fixed_today = date(2024, 7, 15)

    from datetime import datetime as real_datetime

    class _FixedDatetime:
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return real_datetime(2024, 7, 15, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr("app.mlb.ingestion.datetime", _FixedDatetime)

    home = Team(sport=Sport.MLB, mlb_team_id=10, name="H", abbreviation="H")
    away = Team(sport=Sport.MLB, mlb_team_id=11, name="A", abbreviation="A")
    session.add_all([home, away])
    session.flush()

    client = _RecordingClient([])
    sync_schedule(session, client, window_days=7)

    assert client.start == fixed_today - timedelta(days=14)
    assert client.end == fixed_today + timedelta(days=6)
