"""Migration tests for the additive MLB / multi-sport upgrade.

These tests exercise ``ensure_postgres_schema`` (``app/db/migrate.py``) against
a *real* Postgres database, because the migration is a no-op on any other
dialect (``if engine.dialect.name != "postgresql": return``). They are skipped
automatically when no Postgres is reachable (e.g. the SQLite-only CI run), so
the rest of the suite is unaffected.

Two behaviors are pinned:

* **NBA backfill (Req 1.6, 1.7).** A *legacy* database that predates the
  ``sport`` discriminator (its ``teams``/``players``/``games`` tables have no
  ``sport`` column at all) is upgraded by the migration so that every
  pre-existing row is associated with the ``NBA`` sport, and ordinary NBA data
  (rows that carry their ``nba_*_id``) is left fully intact.

* **MLB rows are never swept by the bootstrap wipe (Req 1.7).** The destructive
  "wipe a legacy all-``NULL`` NBA dataset" bootstrap is scoped to ``sport='NBA'``
  rows only. When the wipe fires (every ``sport='NBA'`` team has a ``NULL``
  ``nba_team_id``), MLB teams/players/games and the isolated
  ``mlb_player_game_stats`` rows survive untouched, even though MLB rows
  legitimately carry a ``NULL`` ``nba_team_id``.

Validates: Requirements 1.6, 1.7
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

# Importing the models package registers every table on ``Base.metadata``.
import app.db.models  # noqa: F401
from app.core.config import get_database_url
from app.db.base import Base
from app.db.migrate import ensure_postgres_schema

# Statements that strip the MLB-migration additions so a freshly created schema
# looks like the *legacy* (pre-feature) database the migration must upgrade.
_DROP_SPORT_CHECKS = (
    "ALTER TABLE teams DROP CONSTRAINT IF EXISTS ck_teams_sport_native_id",
    "ALTER TABLE players DROP CONSTRAINT IF EXISTS ck_players_sport_native_id",
    "ALTER TABLE games DROP CONSTRAINT IF EXISTS ck_games_sport_native_id",
)

# Fully strips the discriminator + native MLB columns to emulate a DB created
# before the feature existed (used for the backfill test).
_STRIP_TO_LEGACY = (
    *_DROP_SPORT_CHECKS,
    "DROP TABLE IF EXISTS mlb_player_game_stats",
    "ALTER TABLE teams DROP COLUMN IF EXISTS sport",
    "ALTER TABLE teams DROP COLUMN IF EXISTS mlb_team_id",
    "ALTER TABLE teams DROP COLUMN IF EXISTS abbreviation",
    "ALTER TABLE players DROP COLUMN IF EXISTS sport",
    "ALTER TABLE players DROP COLUMN IF EXISTS mlb_player_id",
    "ALTER TABLE players DROP COLUMN IF EXISTS primary_position",
    "ALTER TABLE games DROP COLUMN IF EXISTS sport",
    "ALTER TABLE games DROP COLUMN IF EXISTS mlb_game_id",
)


@pytest.fixture()
def pg_engine() -> Iterator[Engine]:
    """A clean Postgres schema per test, or skip when none is reachable.

    The migration only acts on Postgres, so without a real server there is
    nothing to verify. We reset ``public`` to a pristine state and let
    ``create_all`` build the current (fully migrated) schema, which each test
    then rewinds to a legacy shape before re-running the migration.
    """
    url = get_database_url()
    if not url.startswith("postgresql"):
        pytest.skip("Migration tests require a Postgres database URL")

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:  # pragma: no cover - environment dependent
        engine.dispose()
        pytest.skip(f"Postgres not reachable for migration tests: {exc}")

    # Pristine schema so prior runs never leak in.
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(engine)

    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        engine.dispose()


def _exec_all(engine: Engine, statements: tuple[str, ...]) -> None:
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def test_legacy_rows_backfill_to_nba(pg_engine: Engine) -> None:
    """Legacy rows with no ``sport`` column all become ``NBA`` and survive.

    Validates: Requirements 1.6, 1.7
    """
    engine = pg_engine
    # Rewind to a pre-feature schema: no sport / mlb columns anywhere.
    _exec_all(engine, _STRIP_TO_LEGACY)

    # Seed ordinary legacy NBA data (each row carries its nba_*_id, so the
    # destructive wipe must NOT fire for this dataset).
    with engine.begin() as conn:
        home = conn.execute(
            text("INSERT INTO teams (name, nba_team_id) VALUES ('Lakers', 1610612747) RETURNING id")
        ).scalar_one()
        away = conn.execute(
            text("INSERT INTO teams (name, nba_team_id) VALUES ('Celtics', 1610612738) RETURNING id")
        ).scalar_one()
        player = conn.execute(
            text(
                "INSERT INTO players (full_name, team_id, nba_player_id) "
                "VALUES ('LeBron James', :t, 2544) RETURNING id"
            ),
            {"t": home},
        ).scalar_one()
        game = conn.execute(
            text(
                "INSERT INTO games (home_team_id, away_team_id, game_date, status, nba_game_id) "
                "VALUES (:h, :a, '2024-01-01', 'Final', '0022300001') RETURNING id"
            ),
            {"h": home, "a": away},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO player_game_stats (player_id, game_id, points, rebounds, assists, minutes) "
                "VALUES (:p, :g, 30, 10, 8, 38.5)"
            ),
            {"p": player, "g": game},
        )

    # Run the migration under test.
    ensure_postgres_schema(engine)

    with engine.connect() as conn:
        # Every pre-existing row is now associated with NBA (Req 1.6, 1.7).
        for table in ("teams", "players", "games"):
            distinct = conn.execute(text(f"SELECT DISTINCT sport FROM {table}")).scalars().all()
            assert distinct == ["NBA"], f"{table} should be backfilled entirely to NBA"
            nulls = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE sport IS NULL")
            ).scalar_one()
            assert nulls == 0, f"{table} must have no NULL sport after backfill"

        # Ordinary NBA data (nba_*_id present) is left intact, never wiped.
        assert conn.execute(text("SELECT COUNT(*) FROM teams")).scalar_one() == 2
        assert conn.execute(text("SELECT COUNT(*) FROM players")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM games")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM player_game_stats")).scalar_one() == 1


def test_mlb_rows_are_never_swept_by_bootstrap_wipe(pg_engine: Engine) -> None:
    """The all-NULL-NBA bootstrap wipe clears NBA rows but spares MLB rows.

    Validates: Requirements 1.7
    """
    engine = pg_engine
    # Legacy shape: drop only the sport/native-id CHECKs so we can seed the
    # pre-wipe state (legacy NBA rows with NULL nba_team_id alongside real MLB
    # rows). The migration re-adds these CHECKs after the wipe.
    _exec_all(engine, _DROP_SPORT_CHECKS)

    with engine.begin() as conn:
        # Legacy NBA dataset: every NBA team has a NULL nba_team_id, which is
        # exactly the condition that arms the destructive bootstrap wipe.
        nba_home = conn.execute(
            text(
                "INSERT INTO teams (name, sport, nba_team_id) "
                "VALUES ('Legacy NBA A', 'NBA', NULL) RETURNING id"
            )
        ).scalar_one()
        nba_away = conn.execute(
            text(
                "INSERT INTO teams (name, sport, nba_team_id) "
                "VALUES ('Legacy NBA B', 'NBA', NULL) RETURNING id"
            )
        ).scalar_one()
        nba_player = conn.execute(
            text(
                "INSERT INTO players (full_name, team_id, sport, nba_player_id) "
                "VALUES ('Legacy NBA Player', :t, 'NBA', NULL) RETURNING id"
            ),
            {"t": nba_home},
        ).scalar_one()
        nba_game = conn.execute(
            text(
                "INSERT INTO games (home_team_id, away_team_id, game_date, status, sport, nba_game_id) "
                "VALUES (:h, :a, '2024-01-01', 'Final', 'NBA', NULL) RETURNING id"
            ),
            {"h": nba_home, "a": nba_away},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO player_game_stats (player_id, game_id, points, rebounds, assists, minutes) "
                "VALUES (:p, :g, 10, 5, 5, 30.0)"
            ),
            {"p": nba_player, "g": nba_game},
        )

        # Real MLB data: carries mlb_*_id with a NULL nba_team_id (legitimate),
        # and must survive the NBA-scoped wipe.
        mlb_home = conn.execute(
            text(
                "INSERT INTO teams (name, sport, mlb_team_id, abbreviation) "
                "VALUES ('Yankees', 'MLB', 147, 'NYY') RETURNING id"
            )
        ).scalar_one()
        mlb_away = conn.execute(
            text(
                "INSERT INTO teams (name, sport, mlb_team_id, abbreviation) "
                "VALUES ('Red Sox', 'MLB', 111, 'BOS') RETURNING id"
            )
        ).scalar_one()
        mlb_player = conn.execute(
            text(
                "INSERT INTO players (full_name, team_id, sport, mlb_player_id, primary_position) "
                "VALUES ('Aaron Judge', :t, 'MLB', 592450, 'RF') RETURNING id"
            ),
            {"t": mlb_home},
        ).scalar_one()
        mlb_game = conn.execute(
            text(
                "INSERT INTO games (home_team_id, away_team_id, game_date, status, sport, mlb_game_id) "
                "VALUES (:h, :a, '2024-04-01', 'Final', 'MLB', '717676') RETURNING id"
            ),
            {"h": mlb_home, "a": mlb_away},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO mlb_player_game_stats "
                "(player_id, game_id, hits, total_bases, rbi, runs, strikeouts_pitcher) "
                "VALUES (:p, :g, 2, 4, 3, 1, 0)"
            ),
            {"p": mlb_player, "g": mlb_game},
        )

    # Run the migration: its bootstrap wipe should clear the legacy NBA rows.
    ensure_postgres_schema(engine)

    with engine.connect() as conn:
        # NBA rows (all-NULL nba_team_id) were swept.
        assert conn.execute(
            text("SELECT COUNT(*) FROM teams WHERE sport = 'NBA'")
        ).scalar_one() == 0
        assert conn.execute(
            text("SELECT COUNT(*) FROM players WHERE sport = 'NBA'")
        ).scalar_one() == 0
        assert conn.execute(
            text("SELECT COUNT(*) FROM games WHERE sport = 'NBA'")
        ).scalar_one() == 0
        # The NBA stat line was removed with its game/player.
        assert conn.execute(text("SELECT COUNT(*) FROM player_game_stats")).scalar_one() == 0

        # MLB rows are untouched by the NBA-scoped wipe (Req 1.7).
        assert conn.execute(
            text("SELECT COUNT(*) FROM teams WHERE sport = 'MLB'")
        ).scalar_one() == 2
        assert conn.execute(
            text("SELECT COUNT(*) FROM players WHERE sport = 'MLB'")
        ).scalar_one() == 1
        assert conn.execute(
            text("SELECT COUNT(*) FROM games WHERE sport = 'MLB'")
        ).scalar_one() == 1
        # The isolated MLB box-score table is never referenced by the wipe.
        assert conn.execute(text("SELECT COUNT(*) FROM mlb_player_game_stats")).scalar_one() == 1
        # The specific MLB game still resolves by its native id.
        assert conn.execute(
            text("SELECT COUNT(*) FROM games WHERE mlb_game_id = '717676'")
        ).scalar_one() == 1

        # The migration re-added the sport/native-id CHECK constraints after the
        # wipe, and the surviving MLB rows satisfy them.
        constraints = conn.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conname IN "
                "('ck_teams_sport_native_id', 'ck_players_sport_native_id', "
                "'ck_games_sport_native_id')"
            )
        ).scalars().all()
        assert set(constraints) == {
            "ck_teams_sport_native_id",
            "ck_players_sport_native_id",
            "ck_games_sport_native_id",
        }
