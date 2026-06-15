"""Property-based test for MLB ingestion batch resilience.

Exercises ``app.mlb.ingestion.run_full_mlb_ingest`` against the shared in-memory
SQLite session using a fake, in-process MLB Stats API client (no network) whose
``boxscore()`` raises :class:`MLBStatsAPIError` for an *arbitrary subset* of the
scheduled games. The orchestration must treat the per-game box-score fetch as a
batch in which a single game's signaled failure is caught and recorded without
aborting the run: every non-failing game is still ingested and every failing
game is recorded in ``MLBIngestSummary.failed_game_ids`` (Requirement 6.5).

Uses a fresh in-memory SQLite session per generated example so worlds never leak
into one another.

Feature: mlb-support, Property 11
Validates: Requirements 6.5
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
from app.db.models import Game, Player
from app.db.models.mlb_player_game_stats import MLBPlayerGameStat
from app.mlb.ingestion import run_full_mlb_ingest
from app.mlb.stats_api_client import MLBStatsAPIError

# Two teams every scheduled game references, so no game is skipped for an
# unknown team (Req 4.6) and the batch is driven purely by box-score outcomes.
_HOME_TEAM_ID = 147
_AWAY_TEAM_ID = 111

# A fixed roster: home and away players that appear in every game's box score.
# Each is seeded via roster ingestion so box lines resolve to a DB player.
_HOME_PLAYERS = [1001, 1002]
_AWAY_PLAYERS = [2001, 2002]
_ALL_PLAYERS = _HOME_PLAYERS + _AWAY_PLAYERS


def _team_payload(mlb_team_id: int, name: str, abbr: str) -> dict:
    return {"id": mlb_team_id, "name": name, "abbreviation": abbr}


def _roster_entry(mlb_player_id: int, position: str) -> dict:
    return {
        "person": {"id": mlb_player_id, "fullName": f"Player {mlb_player_id}"},
        "position": {"abbreviation": position},
    }


def _box_player(mlb_player_id: int) -> dict:
    """A minimal FINAL box line; stat values are fixed (resilience, not shape)."""
    return {
        "person": {"id": mlb_player_id, "fullName": f"Player {mlb_player_id}"},
        "stats": {
            "batting": {"hits": 2, "totalBases": 3, "rbi": 1, "runs": 1},
            "pitching": {"strikeOuts": 4},
        },
    }


def _boxscore() -> dict:
    """A box score listing the home players on home and away players on away."""
    home = {f"ID{pid}": _box_player(pid) for pid in _HOME_PLAYERS}
    away = {f"ID{pid}": _box_player(pid) for pid in _AWAY_PLAYERS}
    return {"home": {"players": home}, "away": {"players": away}}


def _schedule_payload(gid: int) -> dict:
    """A FINAL schedule row so box-score ingestion is attempted for the game."""
    return {
        "game_id": gid,
        "home_id": _HOME_TEAM_ID,
        "away_id": _AWAY_TEAM_ID,
        "game_datetime": "2026-04-10T18:10:00Z",
        "game_date": "2026-04-10",
        "status": "Final",
        "home_score": 5,
        "away_score": 3,
    }


class FakeResilienceClient:
    """In-process ``MLBStatsAPIClient`` whose ``boxscore`` fails for a subset.

    ``teams``/``roster``/``schedule`` always succeed so the batch reaches the
    per-game box-score stage with every game referencing known teams. For each
    ``mlb_game_id`` in ``failing_ids`` the ``boxscore`` call raises
    :class:`MLBStatsAPIError` (the client's signaled-failure contract, Req 6.4),
    while every other game returns a usable box score.
    """

    def __init__(self, game_ids: list[int], failing_ids: set[int]) -> None:
        self._game_ids = game_ids
        self._failing_ids = failing_ids
        self.boxscore_calls: list[int] = []

    def teams(self) -> list[dict]:
        return [
            _team_payload(_HOME_TEAM_ID, "Home Nine", "HOM"),
            _team_payload(_AWAY_TEAM_ID, "Away Nine", "AWY"),
        ]

    def roster(self, mlb_team_id: int) -> list[dict]:
        if mlb_team_id == _HOME_TEAM_ID:
            return [_roster_entry(_HOME_PLAYERS[0], "P"), _roster_entry(_HOME_PLAYERS[1], "CF")]
        if mlb_team_id == _AWAY_TEAM_ID:
            return [_roster_entry(_AWAY_PLAYERS[0], "P"), _roster_entry(_AWAY_PLAYERS[1], "1B")]
        return []

    def schedule(self, start, end):  # noqa: ARG002 - dates unused by the fake
        return [_schedule_payload(gid) for gid in self._game_ids]

    def boxscore(self, mlb_game_id: int) -> dict:
        self.boxscore_calls.append(mlb_game_id)
        if mlb_game_id in self._failing_ids:
            raise MLBStatsAPIError(
                f"simulated signaled failure for mlb_game_id={mlb_game_id}",
                attempts=3,
            )
        return _boxscore()


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


@st.composite
def _world(draw) -> dict:
    """An arbitrary set of games with an arbitrary subset marked to fail."""
    game_ids = draw(
        st.lists(
            st.integers(min_value=1000, max_value=9999),
            min_size=1,
            max_size=8,
            unique=True,
        )
    )
    # Each game independently fails or not -> an arbitrary failing subset
    # (possibly empty, possibly all).
    fail_flags = draw(st.lists(st.booleans(), min_size=len(game_ids), max_size=len(game_ids)))
    failing_ids = {gid for gid, fail in zip(game_ids, fail_flags) if fail}
    return {"game_ids": game_ids, "failing_ids": failing_ids}


@settings(deadline=None, max_examples=100)
@given(world=_world())
def test_property11_single_game_failure_does_not_abort_batch(world: dict) -> None:
    """**Validates: Requirements 6.5**

    Feature: mlb-support, Property 11

    For an arbitrary set of scheduled MLB games and an arbitrary subset whose
    box-score fetch signals a failure, ``run_full_mlb_ingest`` must:

    - attempt the box score for every game (the failing game does not short-
      circuit the loop);
    - record exactly the failing subset in ``failed_game_ids`` and ingest every
      non-failing game (``box_scores_ingested`` counts only the successes);
    - persist box-score stat rows for every non-failing game and none for any
      failing game,

    regardless of which subset (including empty or all) fails.
    """
    game_ids: list[int] = world["game_ids"]
    failing_ids: set[int] = world["failing_ids"]
    success_ids = [gid for gid in game_ids if gid not in failing_ids]

    gen = _fresh_session()
    session = next(gen)
    try:
        client = FakeResilienceClient(game_ids, failing_ids)
        summary = run_full_mlb_ingest(session, client, window_days=7)
        session.commit()

        # The batch reached the box-score stage for every scheduled game; a
        # failure never aborted the loop.
        assert sorted(client.boxscore_calls) == sorted(game_ids)

        # Failed games are recorded; successes are counted separately (Req 6.5).
        assert sorted(summary.failed_game_ids) == sorted(failing_ids)
        assert summary.box_scores_ingested == len(success_ids)
        assert summary.games_synced == len(game_ids)

        # Every non-failing game has one stat row per player with a box entry,
        # and every failing game has none.
        per_game_players = len(_ALL_PLAYERS)
        for gid in game_ids:
            game = session.scalar(select(Game).where(Game.mlb_game_id == str(gid)))
            assert game is not None
            row_count = session.scalar(
                select(func.count())
                .select_from(MLBPlayerGameStat)
                .where(MLBPlayerGameStat.game_id == game.id)
            )
            if gid in failing_ids:
                assert row_count == 0
            else:
                assert row_count == per_game_players

        # Total stat rows and the summary's upsert count reflect only successes.
        total_rows = session.scalar(select(func.count()).select_from(MLBPlayerGameStat))
        assert total_rows == len(success_ids) * per_game_players
        assert summary.stat_rows_upserted == len(success_ids) * per_game_players
    finally:
        gen.close()


# --- focused example test ---------------------------------------------------


def test_batch_resilience_middle_failure_continues(session) -> None:
    """A failure on a middle game still ingests the games before and after it.

    Feature: mlb-support, Property 11
    Validates: Requirements 6.5
    """
    game_ids = [3001, 3002, 3003]
    failing_ids = {3002}
    client = FakeResilienceClient(game_ids, failing_ids)

    summary = run_full_mlb_ingest(session, client, window_days=7)
    session.commit()

    assert sorted(client.boxscore_calls) == game_ids
    assert summary.failed_game_ids == [3002]
    assert summary.box_scores_ingested == 2

    for gid in (3001, 3003):
        game = session.scalar(select(Game).where(Game.mlb_game_id == str(gid)))
        rows = session.scalar(
            select(func.count())
            .select_from(MLBPlayerGameStat)
            .where(MLBPlayerGameStat.game_id == game.id)
        )
        assert rows == len(_ALL_PLAYERS)

    failed_game = session.scalar(select(Game).where(Game.mlb_game_id == "3002"))
    failed_rows = session.scalar(
        select(func.count())
        .select_from(MLBPlayerGameStat)
        .where(MLBPlayerGameStat.game_id == failed_game.id)
    )
    assert failed_rows == 0
