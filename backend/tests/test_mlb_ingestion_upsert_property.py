"""Property-based tests for idempotent MLB team/roster ingestion.

Exercises ``app.mlb.ingestion.sync_teams`` / ``sync_rosters`` against arbitrary
team/roster payloads delivered through an in-process fake MLB Stats API client
(no network). The ingestion of teams and rosters must behave as an *idempotent
keyed upsert*: running it repeatedly with the same payloads converges on the
same keyed set of teams (keyed by ``mlb_team_id``) and players (keyed by
``mlb_player_id``) with no duplicates, and a player observed on a new team has
its team association reassigned rather than duplicated.

Feature: mlb-support, Property 4
Validates: Requirements 3.1, 3.2, 3.3, 3.4
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
from app.db.models import Player, Team
from app.mlb.ingestion import sync_rosters, sync_teams


# --- fake client + fixtures -------------------------------------------------


class FakeClient:
    """In-process stand-in for ``MLBStatsAPIClient`` returning canned payloads."""

    def __init__(self, teams=None, rosters=None):
        self._teams = teams or []
        self._rosters = rosters or {}

    def teams(self):
        return list(self._teams)

    def roster(self, mlb_team_id):
        return list(self._rosters.get(mlb_team_id, []))


def _fresh_session() -> Iterator[Session]:
    """Yield an isolated in-memory SQLite session.

    A brand-new engine per hypothesis example keeps each generated world fully
    independent, so persisted rows from one example never leak into another.
    """
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


def _team_payload(mlb_id, name, abbreviation):
    return {"id": mlb_id, "name": name, "abbreviation": abbreviation}


def _roster_entry(person_id, full_name, position_abbr):
    return {
        "person": {"id": person_id, "fullName": full_name},
        "position": {"abbreviation": position_abbr},
    }


# --- strategies -------------------------------------------------------------


@st.composite
def _league(draw):
    """Generate an arbitrary league plan: distinct teams and distinct players.

    Each player is assigned to exactly one team (by index) so a single roster
    snapshot is unambiguous, mirroring how the real Stats API reports one
    active roster per team.
    """
    team_ids = draw(
        st.lists(st.integers(min_value=1, max_value=10_000), min_size=1, max_size=5, unique=True)
    )
    player_ids = draw(
        st.lists(st.integers(min_value=1, max_value=10_000), min_size=0, max_size=12, unique=True)
    )
    players = []
    for pid in player_ids:
        team_idx = draw(st.integers(min_value=0, max_value=len(team_ids) - 1))
        position = draw(st.sampled_from(["P", "C", "1B", "OF", "SS", "CF"]))
        players.append((pid, team_idx, position))
    return {"team_ids": team_ids, "players": players}


@st.composite
def _league_with_reassignment(draw):
    """A league plan plus a second snapshot where players may switch teams."""
    plan = draw(_league())
    reassigned = []
    for pid, _idx, position in plan["players"]:
        new_idx = draw(st.integers(min_value=0, max_value=len(plan["team_ids"]) - 1))
        reassigned.append((pid, new_idx, position))
    return plan, {"team_ids": plan["team_ids"], "players": reassigned}


def _build_client(plan) -> FakeClient:
    """Materialize a fake client from a league plan."""
    team_ids = plan["team_ids"]
    teams = [_team_payload(tid, f"Team {tid}", f"T{tid % 100:02d}") for tid in team_ids]
    rosters: dict[int, list] = {tid: [] for tid in team_ids}
    for pid, idx, position in plan["players"]:
        rosters[team_ids[idx]].append(_roster_entry(pid, f"Player {pid}", position))
    return FakeClient(teams=teams, rosters=rosters)


def _ingest(session, plan) -> None:
    """Run one full team + roster ingestion pass and commit."""
    client = _build_client(plan)
    by_mlb_id = sync_teams(session, client)
    sync_rosters(session, client, by_mlb_id)
    session.commit()


# --- Property 4: idempotent keyed upsert (Req 3.1, 3.2, 3.3) ----------------


@settings(deadline=None, max_examples=150)
@given(plan=_league(), extra_runs=st.integers(min_value=1, max_value=4))
def test_property4_team_roster_ingestion_is_idempotent_keyed_upsert(plan, extra_runs):
    """**Validates: Requirements 3.1, 3.2, 3.3**

    Feature: mlb-support, Property 4

    Running team + roster ingestion once and then repeating it ``extra_runs``
    more times with the same payloads converges on exactly one team per distinct
    ``mlb_team_id`` and exactly one player per distinct ``mlb_player_id`` (no
    duplicates, Req 3.3). Every team and player carries the ``MLB`` sport
    (Req 3.1, 3.2) and each player is associated with the team whose roster
    listed it (Req 3.2).
    """
    gen = _fresh_session()
    session = next(gen)
    try:
        for _ in range(1 + extra_runs):
            _ingest(session, plan)

        expected_team_ids = set(plan["team_ids"])
        expected_player_ids = {pid for pid, _, _ in plan["players"]}

        teams = session.scalars(select(Team)).all()
        assert session.scalar(select(func.count()).select_from(Team)) == len(expected_team_ids)
        assert {t.mlb_team_id for t in teams} == expected_team_ids
        assert all(t.sport is Sport.MLB for t in teams)

        players = session.scalars(select(Player)).all()
        assert session.scalar(select(func.count()).select_from(Player)) == len(expected_player_ids)
        assert {p.mlb_player_id for p in players} == expected_player_ids
        assert all(p.sport is Sport.MLB for p in players)

        # Each player is keyed to the correct team (Req 3.2).
        team_by_mlb = {t.mlb_team_id: t for t in teams}
        expected_team_of_player = {
            pid: plan["team_ids"][idx] for pid, idx, _ in plan["players"]
        }
        for player in players:
            expected_team = team_by_mlb[expected_team_of_player[player.mlb_player_id]]
            assert player.team_id == expected_team.id
    finally:
        gen.close()


# --- Property 4: player reassignment, still keyed (Req 3.4) -----------------


@settings(deadline=None, max_examples=150)
@given(pair=_league_with_reassignment())
def test_property4_player_reassignment_updates_team_without_duplicates(pair):
    """**Validates: Requirements 3.4**

    Feature: mlb-support, Property 4

    When a later roster snapshot lists a previously-ingested player on a new
    team, ingestion reassigns that player's team association to the team being
    ingested (Req 3.4) rather than inserting a duplicate. The keyed set of
    players (by ``mlb_player_id``) is unchanged in size and each player ends up
    associated with the team from the most recent snapshot.
    """
    plan, plan_reassigned = pair
    gen = _fresh_session()
    session = next(gen)
    try:
        _ingest(session, plan)
        _ingest(session, plan_reassigned)

        expected_player_ids = {pid for pid, _, _ in plan["players"]}
        players = session.scalars(select(Player)).all()
        assert session.scalar(select(func.count()).select_from(Player)) == len(expected_player_ids)
        assert {p.mlb_player_id for p in players} == expected_player_ids

        teams = session.scalars(select(Team)).all()
        team_by_mlb = {t.mlb_team_id: t for t in teams}
        expected_team_of_player = {
            pid: plan_reassigned["team_ids"][idx]
            for pid, idx, _ in plan_reassigned["players"]
        }
        for player in players:
            expected_team = team_by_mlb[expected_team_of_player[player.mlb_player_id]]
            assert player.team_id == expected_team.id
    finally:
        gen.close()
