"""MLB API route tests (Requirements 10.x, Property 3, Property 19)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.enums import Sport
from app.db.models import Game, Player, Team
from app.db.session import get_db
import app.db.session as db_session_module
from app.main import app


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = db_session.get_bind()
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    monkeypatch.setattr(db_session_module, "_engine", engine)
    monkeypatch.setattr(db_session_module, "SessionLocal", factory)
    monkeypatch.setattr(db_session_module, "check_db_connection", lambda: True)
    monkeypatch.setattr("app.db.migrate.ensure_postgres_schema", lambda _engine: None)
    monkeypatch.setattr("app.db.seed_demo.seed_demo_wallet_if_enabled", lambda: None)

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    monkeypatch.setattr(db_session_module, "_engine", None)
    monkeypatch.setattr(db_session_module, "SessionLocal", None)


def _seed_mixed_sports(session: Session) -> tuple[Game, Game]:
    nba_home = Team(name="NBA Home", sport=Sport.NBA, nba_team_id=1)
    nba_away = Team(name="NBA Away", sport=Sport.NBA, nba_team_id=2)
    mlb_home = Team(name="MLB Home", sport=Sport.MLB, mlb_team_id=101, abbreviation="MH")
    mlb_away = Team(name="MLB Away", sport=Sport.MLB, mlb_team_id=102, abbreviation="MA")
    session.add_all([nba_home, nba_away, mlb_home, mlb_away])
    session.flush()

    nba_game = Game(
        home_team_id=nba_home.id,
        away_team_id=nba_away.id,
        game_date=date(2026, 6, 1),
        status="7:30 pm ET",
        sport=Sport.NBA,
        nba_game_id="0022000001",
    )
    mlb_game = Game(
        home_team_id=mlb_home.id,
        away_team_id=mlb_away.id,
        game_date=date(2026, 6, 2),
        game_time_utc=datetime(2026, 6, 2, 23, 0, 0),
        status="Scheduled",
        sport=Sport.MLB,
        mlb_game_id="777001",
    )
    session.add_all([nba_game, mlb_game])
    session.flush()
    return nba_game, mlb_game


class TestSportScopedQueries:
    def test_nba_games_exclude_mlb(self, client: TestClient, db_session: Session) -> None:
        nba_game, mlb_game = _seed_mixed_sports(db_session)
        resp = client.get("/games")
        assert resp.status_code == 200
        ids = {row["id"] for row in resp.json()}
        assert nba_game.id in ids
        assert mlb_game.id not in ids

    def test_mlb_games_exclude_nba(self, client: TestClient, db_session: Session) -> None:
        nba_game, mlb_game = _seed_mixed_sports(db_session)
        resp = client.get("/mlb/games")
        assert resp.status_code == 200
        ids = {row["id"] for row in resp.json()}
        assert mlb_game.id in ids
        assert nba_game.id not in ids

    def test_mlb_games_ordered_by_start_asc(self, client: TestClient, db_session: Session) -> None:
        home = Team(name="H", sport=Sport.MLB, mlb_team_id=201, abbreviation="H")
        away = Team(name="A", sport=Sport.MLB, mlb_team_id=202, abbreviation="A")
        db_session.add_all([home, away])
        db_session.flush()
        later = Game(
            home_team_id=home.id,
            away_team_id=away.id,
            game_date=date(2026, 6, 3),
            game_time_utc=datetime(2026, 6, 3, 23, 0, 0),
            status="Scheduled",
            sport=Sport.MLB,
            mlb_game_id="777002",
        )
        earlier = Game(
            home_team_id=home.id,
            away_team_id=away.id,
            game_date=date(2026, 6, 1),
            game_time_utc=datetime(2026, 6, 1, 18, 0, 0),
            status="Scheduled",
            sport=Sport.MLB,
            mlb_game_id="777003",
        )
        db_session.add_all([later, earlier])
        db_session.flush()

        resp = client.get("/mlb/games")
        ids = [row["id"] for row in resp.json()]
        assert ids.index(earlier.id) < ids.index(later.id)

    def test_unknown_mlb_game_returns_404_without_mutation(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, mlb_game = _seed_mixed_sports(db_session)
        before = db_session.get(Game, mlb_game.id)
        assert before is not None
        assert client.get("/mlb/games/999999/markets").status_code == 404
        assert client.get("/mlb/games/999999/prop-lines").status_code == 404
        assert db_session.get(Game, mlb_game.id) is not None

    def test_nba_route_404_for_mlb_game_id(self, client: TestClient, db_session: Session) -> None:
        _, mlb_game = _seed_mixed_sports(db_session)
        assert client.get(f"/games/{mlb_game.id}/markets").status_code == 404

    def test_empty_mlb_collections_return_200_empty_list(
        self, client: TestClient, db_session: Session
    ) -> None:
        assert client.get("/mlb/games").json() == []
        assert client.get("/mlb/teams").json() == []
        assert client.get("/mlb/players").json() == []


class TestMlbApiWiring:
    def test_mlb_markets_and_prop_lines_for_seeded_game(
        self, client: TestClient, db_session: Session
    ) -> None:
        _, mlb_game = _seed_mixed_sports(db_session)
        markets = client.get(f"/mlb/games/{mlb_game.id}/markets")
        assert markets.status_code == 200
        body = markets.json()
        assert body["game"]["id"] == mlb_game.id
        assert "moneyline" in body and "spread" in body and "total" in body

        props = client.get(f"/mlb/games/{mlb_game.id}/prop-lines")
        assert props.status_code == 200
        assert props.json()["game"]["id"] == mlb_game.id

    def test_mlb_players_list_is_sport_scoped(self, client: TestClient, db_session: Session) -> None:
        team = Team(name="MLB T", sport=Sport.MLB, mlb_team_id=301, abbreviation="MT")
        nba_team = Team(name="NBA T", sport=Sport.NBA, nba_team_id=99)
        db_session.add_all([team, nba_team])
        db_session.flush()
        mlb_player = Player(
            full_name="Slugger",
            team_id=team.id,
            sport=Sport.MLB,
            mlb_player_id=9001,
            primary_position="OF",
        )
        nba_player = Player(
            full_name="Hooper",
            team_id=nba_team.id,
            sport=Sport.NBA,
            nba_player_id=9002,
        )
        db_session.add_all([mlb_player, nba_player])
        db_session.flush()

        resp = client.get("/mlb/players")
        ids = {row["id"] for row in resp.json()}
        assert mlb_player.id in ids
        assert nba_player.id not in ids
