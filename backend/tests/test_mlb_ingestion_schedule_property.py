"""Property-based and example tests for MLB schedule/game ingestion.

Exercises ``app.mlb.ingestion.sync_schedule`` against the shared in-memory
SQLite session using a fake, in-process MLB Stats API client (no network).
Schedule ingestion must be an *idempotent keyed upsert* (keyed by MLB_Game_ID)
that classifies each game's status into exactly one PRE_GAME / LIVE / FINAL
class and handles run totals per the spec: overwrite stored totals when both are
reported (and the game has started), leave them unchanged when not reported,
and store the final reported totals while FINAL.

Feature: mlb-support, Property 5
Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5
"""

from __future__ import annotations

from collections.abc import Iterator

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

# Importing the models package registers every table on ``Base.metadata``.
import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.enums import Sport
from app.db.models import Game, Team
from app.mlb.ingestion import sync_schedule
from app.mlb.status import MLBGameStatus, classify_status


# Raw Stats API status text -> the class ``classify_status`` assigns it.
_STATUS_CASES: dict[str, MLBGameStatus] = {
    "Scheduled": MLBGameStatus.PRE_GAME,
    "Pre-Game": MLBGameStatus.PRE_GAME,
    "Warmup": MLBGameStatus.PRE_GAME,
    "In Progress": MLBGameStatus.LIVE,
    "Manager Challenge": MLBGameStatus.LIVE,
    "Final": MLBGameStatus.FINAL,
    "Game Over": MLBGameStatus.FINAL,
}
_STATUS_TEXTS = sorted(_STATUS_CASES)


class FakeScheduleClient:
    """In-process stand-in for ``MLBStatsAPIClient`` returning canned schedule rows."""

    def __init__(self, payloads):
        self._payloads = payloads

    def schedule(self, start, end):  # noqa: ARG002 - dates unused by the fake
        return list(self._payloads)


def _fresh_session() -> Iterator[Session]:
    """Yield an isolated in-memory SQLite session per hypothesis example."""
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


def _seed_team(session: Session, mlb_team_id: int) -> Team:
    team = Team(
        name=f"MLB Team {mlb_team_id}",
        sport=Sport.MLB,
        mlb_team_id=mlb_team_id,
        abbreviation=f"M{mlb_team_id % 100:02d}",
    )
    session.add(team)
    return team


def _model_totals(rounds: list[dict]) -> tuple[int | None, int | None]:
    """Reference model for stored run totals after applying ``rounds`` in order.

    Mirrors ``_apply_run_totals``: a PRE_GAME sync never touches the totals; a
    LIVE/FINAL sync overwrites both totals only when BOTH are reported, and
    otherwise leaves them unchanged (Req 4.4, 4.5).
    """
    home: int | None = None
    away: int | None = None
    for r in rounds:
        cls = _STATUS_CASES[r["status"]]
        if cls is MLBGameStatus.PRE_GAME:
            continue
        if r["home_score"] is not None and r["away_score"] is not None:
            home, away = r["home_score"], r["away_score"]
    return home, away


# --- strategies -------------------------------------------------------------

_score = st.one_of(st.none(), st.integers(min_value=0, max_value=20))
_round = st.fixed_dictionaries(
    {
        "status": st.sampled_from(_STATUS_TEXTS),
        "home_score": _score,
        "away_score": _score,
    }
)


@st.composite
def _world(draw) -> dict:
    n_teams = draw(st.integers(min_value=2, max_value=5))
    team_ids = list(range(1, n_teams + 1))
    gids = draw(
        st.lists(st.integers(min_value=1000, max_value=9999), min_size=1, max_size=6, unique=True)
    )
    games = []
    for gid in gids:
        home_known = draw(st.booleans())
        away_known = draw(st.booleans())
        # Known ids come from the seeded pool; unknown ids live in disjoint
        # ranges that never collide with the pool, so the game is skipped.
        home_id = draw(st.sampled_from(team_ids)) if home_known else draw(
            st.integers(min_value=10_000, max_value=20_000)
        )
        away_id = draw(st.sampled_from(team_ids)) if away_known else draw(
            st.integers(min_value=20_001, max_value=30_000)
        )
        games.append(
            {
                "gid": gid,
                "home_id": home_id,
                "away_id": away_id,
                "known": home_known and away_known,
                "day": draw(st.integers(min_value=1, max_value=28)),
                "hour": draw(st.integers(min_value=0, max_value=23)),
                "r1": draw(_round),
                "r2": draw(_round),
            }
        )
    return {"team_ids": team_ids, "games": games}


def _payloads(games: list[dict], round_key: str) -> list[dict]:
    out = []
    for g in games:
        r = g[round_key]
        day = g["day"]
        out.append(
            {
                "game_id": g["gid"],
                "home_id": g["home_id"],
                "away_id": g["away_id"],
                "game_datetime": f"2026-04-{day:02d}T{g['hour']:02d}:10:00Z",
                "game_date": f"2026-04-{day:02d}",
                "status": r["status"],
                "home_score": r["home_score"],
                "away_score": r["away_score"],
            }
        )
    return out


# --- Property 5 -------------------------------------------------------------


@settings(deadline=None, max_examples=120)
@given(world=_world())
def test_property5_schedule_idempotent_upsert_status_and_totals(world: dict) -> None:
    """**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**

    Feature: mlb-support, Property 5

    For an arbitrary world of MLB teams and scheduled games (some referencing
    unknown teams), ingesting a first schedule, then an updated schedule, then
    the updated schedule a second time must:

    - upsert exactly one ``Game`` row per MLB_Game_ID whose both teams are known,
      and create no row for a game referencing an unknown team (idempotent keyed
      upsert, no duplicates -- Req 4.1, 4.3, 4.6);
    - classify each stored status into exactly one PRE_GAME / LIVE / FINAL class
      that matches the most recent ingested status (Req 4.2);
    - store run totals that follow the overwrite-when-reported /
      leave-unchanged-otherwise rule, with final reported totals while FINAL
      (Req 4.4, 4.5);
    - be idempotent: re-ingesting the same schedule changes nothing.
    """
    gen = _fresh_session()
    session = next(gen)
    try:
        team_ids = world["team_ids"]
        games = world["games"]

        for tid in team_ids:
            _seed_team(session, tid)
        session.commit()

        sync_schedule(session, FakeScheduleClient(_payloads(games, "r1")), window_days=7)
        session.commit()
        sync_schedule(session, FakeScheduleClient(_payloads(games, "r2")), window_days=7)
        session.commit()

        valid = [g for g in games if g["known"]]
        valid_gids = {g["gid"] for g in valid}

        rows = session.scalars(select(Game).where(Game.sport == Sport.MLB)).all()
        # Keyed upsert with no duplicates: exactly one row per valid MLB_Game_ID,
        # and nothing persisted for unknown-team games.
        assert len(rows) == len(valid_gids)
        assert {int(r.mlb_game_id) for r in rows} == valid_gids

        for g in valid:
            game = session.scalar(select(Game).where(Game.mlb_game_id == str(g["gid"])))
            assert game is not None
            # Status reflects the latest ingested round and is single-valued.
            assert game.status == g["r2"]["status"]
            assert classify_status(None, game.status) is _STATUS_CASES[g["r2"]["status"]]
            # Scheduled start is stored/updated.
            assert game.game_time_utc is not None
            # Run totals follow overwrite-when-reported / leave-unchanged rules.
            exp_home, exp_away = _model_totals([g["r1"], g["r2"]])
            assert (game.home_score, game.away_score) == (exp_home, exp_away)

        # Idempotency: re-ingesting the identical schedule changes nothing.
        snapshot = {
            r.mlb_game_id: (
                r.home_team_id,
                r.away_team_id,
                r.game_date,
                r.status,
                r.home_score,
                r.away_score,
            )
            for r in rows
        }
        count_before = session.scalar(select(func.count()).select_from(Game))

        sync_schedule(session, FakeScheduleClient(_payloads(games, "r2")), window_days=7)
        session.commit()

        assert session.scalar(select(func.count()).select_from(Game)) == count_before
        after = {
            r.mlb_game_id: (
                r.home_team_id,
                r.away_team_id,
                r.game_date,
                r.status,
                r.home_score,
                r.away_score,
            )
            for r in session.scalars(select(Game).where(Game.sport == Sport.MLB)).all()
        }
        assert after == snapshot
    finally:
        gen.close()


# --- focused example tests --------------------------------------------------


def _schedule_payload(gid, home_id, away_id, status, home_score=None, away_score=None):
    return {
        "game_id": gid,
        "home_id": home_id,
        "away_id": away_id,
        "game_datetime": "2026-04-10T18:10:00Z",
        "game_date": "2026-04-10",
        "status": status,
        "home_score": home_score,
        "away_score": away_score,
    }


def test_schedule_pre_game_leaves_totals_none(session):
    """A PRE_GAME game never stores run totals even if scores leak in (Req 4.4)."""
    _seed_team(session, 1)
    _seed_team(session, 2)
    session.commit()

    client = FakeScheduleClient([_schedule_payload(5001, 1, 2, "Scheduled", 3, 2)])
    sync_schedule(session, client, window_days=7)
    session.commit()

    game = session.scalar(select(Game).where(Game.mlb_game_id == "5001"))
    assert classify_status(None, game.status) is MLBGameStatus.PRE_GAME
    assert game.home_score is None and game.away_score is None


def test_schedule_final_sets_final_totals(session):
    """While FINAL, the reported run totals are stored as final values (Req 4.5)."""
    _seed_team(session, 1)
    _seed_team(session, 2)
    session.commit()

    client = FakeScheduleClient([_schedule_payload(5002, 1, 2, "Final", 7, 4)])
    sync_schedule(session, client, window_days=7)
    session.commit()

    game = session.scalar(select(Game).where(Game.mlb_game_id == "5002"))
    assert classify_status(None, game.status) is MLBGameStatus.FINAL
    assert (game.home_score, game.away_score) == (7, 4)


def test_schedule_live_partial_scores_left_unchanged(session):
    """A LIVE update with only one side reported leaves both totals unchanged (Req 4.4)."""
    _seed_team(session, 1)
    _seed_team(session, 2)
    session.commit()

    # First: a complete LIVE report establishes totals.
    sync_schedule(
        session,
        FakeScheduleClient([_schedule_payload(5003, 1, 2, "In Progress", 2, 1)]),
        window_days=7,
    )
    session.commit()
    # Then: a report missing the away score must not overwrite the stored totals.
    sync_schedule(
        session,
        FakeScheduleClient([_schedule_payload(5003, 1, 2, "In Progress", 5, None)]),
        window_days=7,
    )
    session.commit()

    game = session.scalar(select(Game).where(Game.mlb_game_id == "5003"))
    assert (game.home_score, game.away_score) == (2, 1)


def test_schedule_update_in_place_no_duplicate(session):
    """An existing game is updated in place (status/start), never duplicated (Req 4.3)."""
    _seed_team(session, 1)
    _seed_team(session, 2)
    session.commit()

    sync_schedule(
        session,
        FakeScheduleClient([_schedule_payload(5004, 1, 2, "Scheduled")]),
        window_days=7,
    )
    session.commit()
    sync_schedule(
        session,
        FakeScheduleClient([_schedule_payload(5004, 1, 2, "Final", 6, 3)]),
        window_days=7,
    )
    session.commit()

    assert session.scalar(select(func.count()).select_from(Game)) == 1
    game = session.scalar(select(Game).where(Game.mlb_game_id == "5004"))
    assert game.status == "Final"
    assert (game.home_score, game.away_score) == (6, 3)


def test_schedule_unknown_team_skipped_no_row(session):
    """A game referencing an unknown team is skipped and persists no row (Req 4.6)."""
    _seed_team(session, 1)
    session.commit()

    client = FakeScheduleClient([_schedule_payload(5005, 1, 9999, "Scheduled")])
    sync_schedule(session, client, window_days=7)
    session.commit()

    assert session.scalar(select(func.count()).select_from(Game)) == 0
