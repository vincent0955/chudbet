"""Unit tests for MLB team and roster ingestion (Requirements 3.1-3.5).

Exercises ``app.mlb.ingestion.sync_teams`` / ``sync_rosters`` against the shared
in-memory SQLite session fixture using a fake, in-process MLB Stats API client
(no network). Covers the keyed upsert, idempotency, cross-team reassignment, and
the empty-roster diagnostic path.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.db.enums import Sport
from app.db.models import Player, Team
from app.mlb.ingestion import sync_rosters, sync_teams


class FakeClient:
    """In-process stand-in for ``MLBStatsAPIClient`` returning canned payloads."""

    def __init__(self, teams=None, rosters=None):
        self._teams = teams or []
        self._rosters = rosters or {}

    def teams(self):
        return list(self._teams)

    def roster(self, mlb_team_id):
        return list(self._rosters.get(mlb_team_id, []))


def _team_payload(mlb_id, name, abbreviation):
    return {"id": mlb_id, "name": name, "abbreviation": abbreviation}


def _roster_entry(person_id, full_name, position_abbr):
    return {
        "person": {"id": person_id, "fullName": full_name},
        "position": {"abbreviation": position_abbr, "type": "Pitcher", "name": "Pitcher"},
    }


# --- sync_teams (Req 3.1, 3.3) ---------------------------------------------


def test_sync_teams_inserts_mlb_teams(session):
    client = FakeClient(
        teams=[
            _team_payload(147, "New York Yankees", "NYY"),
            _team_payload(111, "Boston Red Sox", "BOS"),
        ]
    )

    by_mlb_id = sync_teams(session, client)
    session.commit()

    assert set(by_mlb_id) == {147, 111}
    rows = session.scalars(select(Team)).all()
    assert len(rows) == 2
    yankees = session.scalar(select(Team).where(Team.mlb_team_id == 147))
    assert yankees.name == "New York Yankees"
    assert yankees.abbreviation == "NYY"
    assert yankees.sport is Sport.MLB
    assert yankees.nba_team_id is None


def test_sync_teams_is_idempotent_keyed_upsert(session):
    """Re-running with an updated name updates in place, never duplicates (Req 3.3)."""
    client = FakeClient(teams=[_team_payload(147, "NY Yankees", "NYY")])
    sync_teams(session, client)
    session.commit()

    client2 = FakeClient(teams=[_team_payload(147, "New York Yankees", "NYY")])
    sync_teams(session, client2)
    session.commit()

    assert session.scalar(select(func.count()).select_from(Team)) == 1
    team = session.scalar(select(Team).where(Team.mlb_team_id == 147))
    assert team.name == "New York Yankees"


def test_sync_teams_skips_payload_missing_id_or_name(session, caplog):
    client = FakeClient(
        teams=[
            {"name": "No Id", "abbreviation": "NID"},
            {"id": 111, "abbreviation": "BOS"},  # missing name
            _team_payload(147, "New York Yankees", "NYY"),
        ]
    )
    with caplog.at_level(logging.WARNING):
        by_mlb_id = sync_teams(session, client)
    session.commit()

    assert set(by_mlb_id) == {147}
    assert session.scalar(select(func.count()).select_from(Team)) == 1


# --- sync_rosters (Req 3.2-3.5) --------------------------------------------


def test_sync_rosters_inserts_players_with_team_and_position(session):
    client = FakeClient(
        teams=[_team_payload(147, "Yankees", "NYY")],
        rosters={
            147: [
                _roster_entry(592450, "Aaron Judge", "CF"),
                _roster_entry(543037, "Gerrit Cole", "P"),
            ]
        },
    )
    by_mlb_id = sync_teams(session, client)
    sync_rosters(session, client, by_mlb_id)
    session.commit()

    players = session.scalars(select(Player)).all()
    assert len(players) == 2
    judge = session.scalar(select(Player).where(Player.mlb_player_id == 592450))
    assert judge.full_name == "Aaron Judge"
    assert judge.primary_position == "CF"
    assert judge.sport is Sport.MLB
    assert judge.team_id == by_mlb_id[147].id
    assert judge.nba_player_id is None


def test_sync_rosters_idempotent_upsert_updates_in_place(session):
    client = FakeClient(
        teams=[_team_payload(147, "Yankees", "NYY")],
        rosters={147: [_roster_entry(592450, "A. Judge", "RF")]},
    )
    by_mlb_id = sync_teams(session, client)
    sync_rosters(session, client, by_mlb_id)
    session.commit()

    client2 = FakeClient(
        teams=[_team_payload(147, "Yankees", "NYY")],
        rosters={147: [_roster_entry(592450, "Aaron Judge", "CF")]},
    )
    by_mlb_id2 = sync_teams(session, client2)
    sync_rosters(session, client2, by_mlb_id2)
    session.commit()

    assert session.scalar(select(func.count()).select_from(Player)) == 1
    judge = session.scalar(select(Player).where(Player.mlb_player_id == 592450))
    assert judge.full_name == "Aaron Judge"
    assert judge.primary_position == "CF"


def test_sync_rosters_reassigns_player_to_new_team(session):
    """A player found on a new team has its team association updated (Req 3.4)."""
    client = FakeClient(
        teams=[_team_payload(147, "Yankees", "NYY"), _team_payload(111, "Red Sox", "BOS")],
        rosters={147: [_roster_entry(592450, "Aaron Judge", "CF")], 111: []},
    )
    by_mlb_id = sync_teams(session, client)
    sync_rosters(session, client, by_mlb_id)
    session.commit()
    assert session.scalar(select(Player).where(Player.mlb_player_id == 592450)).team_id == by_mlb_id[147].id

    # Judge now appears on the Red Sox roster instead.
    client2 = FakeClient(
        teams=[_team_payload(147, "Yankees", "NYY"), _team_payload(111, "Red Sox", "BOS")],
        rosters={147: [], 111: [_roster_entry(592450, "Aaron Judge", "CF")]},
    )
    by_mlb_id2 = sync_teams(session, client2)
    sync_rosters(session, client2, by_mlb_id2)
    session.commit()

    assert session.scalar(select(func.count()).select_from(Player)) == 1
    judge = session.scalar(select(Player).where(Player.mlb_player_id == 592450))
    assert judge.team_id == by_mlb_id2[111].id


def test_sync_rosters_empty_roster_inserts_nothing_and_logs(session, caplog):
    """A team with no roster entries completes with a diagnostic and no inserts (Req 3.5)."""
    client = FakeClient(
        teams=[_team_payload(147, "Yankees", "NYY")],
        rosters={147: []},
    )
    by_mlb_id = sync_teams(session, client)
    with caplog.at_level(logging.INFO):
        sync_rosters(session, client, by_mlb_id)
    session.commit()

    assert session.scalar(select(func.count()).select_from(Player)) == 0
    assert any("no roster entries" in r.message for r in caplog.records)
    assert any("Yankees" in r.getMessage() for r in caplog.records)
