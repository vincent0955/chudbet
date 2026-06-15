"""Unit tests for MLB box-score ingestion (Requirements 5.1-5.6).

Exercises ``app.mlb.ingestion.ingest_box_score_for_game`` against the shared
in-memory SQLite session fixture using a fake, in-process MLB Stats API client
(no network). Covers the status-driven upsert rules (PRE_GAME no-op, LIVE
``max``, FINAL overwrite), the unreported-stat-to-zero shape, the unknown-player
skip, and the no-usable-data path.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest
from sqlalchemy import func, select

from app.db.enums import Sport
from app.db.models import Game, Player, Team
from app.db.models.mlb_player_game_stats import MLBPlayerGameStat
from app.mlb.ingestion import ingest_box_score_for_game


class FakeClient:
    """In-process stand-in for ``MLBStatsAPIClient`` returning a canned box score."""

    def __init__(self, boxscore=None):
        self._boxscore = boxscore if boxscore is not None else {}
        self.calls = 0

    def boxscore(self, mlb_game_id):
        self.calls += 1
        return self._boxscore


# --- fixtures / builders ----------------------------------------------------


def _make_team(session, mlb_team_id, name):
    team = Team(sport=Sport.MLB, mlb_team_id=mlb_team_id, name=name, abbreviation=name[:3].upper())
    session.add(team)
    session.flush()
    return team


def _make_player(session, mlb_player_id, full_name, team, position="CF"):
    player = Player(
        sport=Sport.MLB,
        mlb_player_id=mlb_player_id,
        full_name=full_name,
        primary_position=position,
        team_id=team.id,
    )
    session.add(player)
    session.flush()
    return player


def _make_game(session, mlb_game_id, home, away, status):
    game = Game(
        sport=Sport.MLB,
        mlb_game_id=str(mlb_game_id),
        home_team_id=home.id,
        away_team_id=away.id,
        game_date=date(2024, 7, 1),
        status=status,
    )
    session.add(game)
    session.flush()
    return game


def _box_player(person_id, *, hits=None, total_bases=None, rbi=None, runs=None, strikeouts=None):
    batting = {}
    if hits is not None:
        batting["hits"] = hits
    if total_bases is not None:
        batting["totalBases"] = total_bases
    if rbi is not None:
        batting["rbi"] = rbi
    if runs is not None:
        batting["runs"] = runs
    pitching = {}
    if strikeouts is not None:
        pitching["strikeOuts"] = strikeouts
    return {
        "person": {"id": person_id, "fullName": f"Player {person_id}"},
        "stats": {"batting": batting, "pitching": pitching},
    }


def _boxscore(home_players=None, away_players=None):
    def _wrap(players):
        return {f"ID{p['person']['id']}": p for p in (players or [])}

    return {
        "home": {"players": _wrap(home_players)},
        "away": {"players": _wrap(away_players)},
    }


@pytest.fixture()
def seeded(session):
    home = _make_team(session, 147, "Yankees")
    away = _make_team(session, 111, "Red Sox")
    judge = _make_player(session, 592450, "Aaron Judge", home, position="CF")
    cole = _make_player(session, 543037, "Gerrit Cole", home, position="P")
    session.commit()
    return {"home": home, "away": away, "judge": judge, "cole": cole}


# --- Req 5.1: keyed upsert, unreported -> 0 ---------------------------------


def test_ingest_creates_one_record_per_player_with_unreported_zero(session, seeded):
    client = FakeClient(
        _boxscore(
            home_players=[
                _box_player(592450, hits=2, total_bases=5, rbi=3, runs=1),  # batter
                _box_player(543037, strikeouts=8),  # pitcher, no batting reported
            ]
        )
    )
    game = _make_game(session, 776543, seeded["home"], seeded["away"], "Final")

    count = ingest_box_score_for_game(session, client, game)
    session.commit()

    assert count == 2
    judge_stat = session.scalar(
        select(MLBPlayerGameStat).where(MLBPlayerGameStat.player_id == seeded["judge"].id)
    )
    assert (judge_stat.hits, judge_stat.total_bases, judge_stat.rbi, judge_stat.runs) == (2, 5, 3, 1)
    assert judge_stat.strikeouts_pitcher == 0  # unreported -> 0

    cole_stat = session.scalar(
        select(MLBPlayerGameStat).where(MLBPlayerGameStat.player_id == seeded["cole"].id)
    )
    assert cole_stat.strikeouts_pitcher == 8
    assert (cole_stat.hits, cole_stat.total_bases, cole_stat.rbi, cole_stat.runs) == (0, 0, 0, 0)


def test_ingest_is_idempotent_keyed_upsert_final(session, seeded):
    box = _boxscore(home_players=[_box_player(592450, hits=2, total_bases=4, rbi=1, runs=1)])
    game = _make_game(session, 776543, seeded["home"], seeded["away"], "Final")

    ingest_box_score_for_game(session, FakeClient(box), game)
    session.commit()
    ingest_box_score_for_game(session, FakeClient(box), game)
    session.commit()

    assert session.scalar(select(func.count()).select_from(MLBPlayerGameStat)) == 1


# --- Req 5.2: while LIVE, max(stored, new) ----------------------------------


def test_live_update_takes_max_of_stored_and_new(session, seeded):
    game = _make_game(session, 776543, seeded["home"], seeded["away"], "In Progress")

    ingest_box_score_for_game(
        session, FakeClient(_boxscore(home_players=[_box_player(592450, hits=2, total_bases=3, rbi=1, runs=2)])), game
    )
    session.commit()

    # A later LIVE pull reports a lower hits (regression) but higher total_bases.
    ingest_box_score_for_game(
        session, FakeClient(_boxscore(home_players=[_box_player(592450, hits=1, total_bases=5, rbi=1, runs=2)])), game
    )
    session.commit()

    stat = session.scalar(select(MLBPlayerGameStat).where(MLBPlayerGameStat.player_id == seeded["judge"].id))
    assert stat.hits == 2  # max(2, 1)
    assert stat.total_bases == 5  # max(3, 5)


# --- Req 5.3: while FINAL, overwrite even if lower --------------------------


def test_final_overwrites_even_when_lower(session, seeded):
    game = _make_game(session, 776543, seeded["home"], seeded["away"], "In Progress")
    ingest_box_score_for_game(
        session, FakeClient(_boxscore(home_players=[_box_player(592450, hits=3, total_bases=6, rbi=2, runs=2)])), game
    )
    session.commit()

    # Game goes final with corrected (lower) values.
    game.status = "Final"
    session.flush()
    ingest_box_score_for_game(
        session, FakeClient(_boxscore(home_players=[_box_player(592450, hits=2, total_bases=4, rbi=1, runs=1)])), game
    )
    session.commit()

    stat = session.scalar(select(MLBPlayerGameStat).where(MLBPlayerGameStat.player_id == seeded["judge"].id))
    assert (stat.hits, stat.total_bases, stat.rbi, stat.runs) == (2, 4, 1, 1)


# --- Req 5.4: while PRE_GAME, create/modify nothing -------------------------


def test_pre_game_creates_or_modifies_nothing(session, seeded):
    client = FakeClient(_boxscore(home_players=[_box_player(592450, hits=2)]))
    game = _make_game(session, 776543, seeded["home"], seeded["away"], "Scheduled")

    count = ingest_box_score_for_game(session, client, game)
    session.commit()

    assert count == 0
    assert client.calls == 0  # no request issued for a pre-game
    assert session.scalar(select(func.count()).select_from(MLBPlayerGameStat)) == 0


# --- Req 5.5: skip unknown player, leave others intact ----------------------


def test_unknown_player_is_skipped_others_intact(session, seeded, caplog):
    client = FakeClient(
        _boxscore(
            home_players=[
                _box_player(592450, hits=2, total_bases=3),  # known
                _box_player(999999, hits=1, total_bases=1),  # absent from DB
            ]
        )
    )
    game = _make_game(session, 776543, seeded["home"], seeded["away"], "Final")

    with caplog.at_level(logging.WARNING):
        count = ingest_box_score_for_game(session, client, game)
    session.commit()

    assert count == 1
    assert session.scalar(select(func.count()).select_from(MLBPlayerGameStat)) == 1
    known = session.scalar(select(MLBPlayerGameStat).where(MLBPlayerGameStat.player_id == seeded["judge"].id))
    assert known.hits == 2
    assert any("999999" in r.getMessage() and "776543" in r.getMessage() for r in caplog.records)


# --- Req 5.6: no usable data, existing unchanged ----------------------------


def test_no_usable_data_leaves_existing_unchanged(session, seeded, caplog):
    game = _make_game(session, 776543, seeded["home"], seeded["away"], "Final")
    # Seed an existing stat row from a prior good pull.
    ingest_box_score_for_game(
        session, FakeClient(_boxscore(home_players=[_box_player(592450, hits=2, total_bases=4)])), game
    )
    session.commit()

    # A later pull returns an empty/unusable payload (no player entries).
    with caplog.at_level(logging.WARNING):
        count = ingest_box_score_for_game(session, FakeClient({"home": {"players": {}}, "away": {"players": {}}}), game)
    session.commit()

    assert count == 0
    stat = session.scalar(select(MLBPlayerGameStat).where(MLBPlayerGameStat.player_id == seeded["judge"].id))
    assert (stat.hits, stat.total_bases) == (2, 4)  # unchanged
    assert any("776543" in r.getMessage() for r in caplog.records)
