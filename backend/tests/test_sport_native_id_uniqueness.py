"""Property-based tests for cross-sport sport-native identifier uniqueness.

Feature: mlb-support, Property 2
Property 2: Sport-native identifiers are unique only within a sport.

Validates: Requirements 1.3

The schema stores each entity's sport-native identifier in a per-sport column
(``nba_*_id`` / ``mlb_*_id``) guarded by a per-sport partial unique index. As a
result an MLB native id value may equal an NBA native id value on two different
records without raising a uniqueness conflict, while two records of the *same*
sport that share a native id value are rejected.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.db.models  # noqa: F401  (registers all tables on Base.metadata)
from app.db.base import Base
from app.db.enums import Sport
from app.db.models.game import Game
from app.db.models.player import Player
from app.db.models.team import Team

# Native-id values stay comfortably inside the integer / VARCHAR(16) bounds.
native_ids = st.integers(min_value=1, max_value=2_000_000_000)

ENTITY_KINDS = ["team", "player", "game"]


@contextmanager
def fresh_session() -> Iterator[Session]:
    """A throwaway in-memory DB per Hypothesis example for full isolation."""

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


def _make_team(sport: Sport, native_id: int) -> Team:
    if sport is Sport.NBA:
        return Team(name="NBA Team", sport=Sport.NBA, nba_team_id=native_id)
    return Team(name="MLB Team", sport=Sport.MLB, mlb_team_id=native_id, abbreviation="MLB")


def _host_team(session: Session, sport: Sport, native_id: int) -> Team:
    """Persist a parent team a player/game can reference via FK."""

    team = _make_team(sport, native_id)
    session.add(team)
    session.flush()
    return team


def _make_player(session: Session, sport: Sport, native_id: int, *, team_offset: int) -> Player:
    # The host team needs its own unique native id, distinct from the player's.
    host = _host_team(session, sport, native_id + team_offset)
    if sport is Sport.NBA:
        return Player(
            full_name="NBA Player", team_id=host.id, sport=Sport.NBA, nba_player_id=native_id
        )
    return Player(
        full_name="MLB Player",
        team_id=host.id,
        sport=Sport.MLB,
        mlb_player_id=native_id,
        primary_position="P",
    )


def _make_game(session: Session, sport: Sport, native_id: int, *, team_offset: int) -> Game:
    home = _host_team(session, sport, native_id + team_offset)
    away = _host_team(session, sport, native_id + team_offset + 1)
    common = dict(
        home_team_id=home.id,
        away_team_id=away.id,
        game_date=date(2024, 7, 1),
        status="Scheduled",
    )
    if sport is Sport.NBA:
        return Game(sport=Sport.NBA, nba_game_id=str(native_id), **common)
    return Game(sport=Sport.MLB, mlb_game_id=str(native_id), **common)


def _make_entity(session: Session, kind: str, sport: Sport, native_id: int, *, team_offset: int):
    if kind == "team":
        return _make_team(sport, native_id)
    if kind == "player":
        return _make_player(session, sport, native_id, team_offset=team_offset)
    return _make_game(session, sport, native_id, team_offset=team_offset)


@pytest.mark.parametrize("kind", ENTITY_KINDS)
@settings(max_examples=150, deadline=None)
@given(native_id=native_ids)
def test_cross_sport_native_id_collision_is_allowed(kind: str, native_id: int) -> None:
    """An MLB native id may equal an NBA native id on two different records.

    Feature: mlb-support, Property 2
    Validates: Requirements 1.3
    """

    with fresh_session() as session:
        # Offsets keep the FK host teams' own native ids from colliding with
        # each other or the entity under test within the same sport.
        nba_entity = _make_entity(session, kind, Sport.NBA, native_id, team_offset=1_000_000_000)
        mlb_entity = _make_entity(session, kind, Sport.MLB, native_id, team_offset=1_000_000_000)
        session.add_all([nba_entity, mlb_entity])

        # The shared numeric/string id value across the two sports must commit
        # without a uniqueness conflict.
        session.commit()

        assert nba_entity.id is not None
        assert mlb_entity.id is not None
        assert nba_entity.id != mlb_entity.id


@pytest.mark.parametrize("kind", ENTITY_KINDS)
@pytest.mark.parametrize("sport", [Sport.NBA, Sport.MLB])
@settings(max_examples=150, deadline=None)
@given(native_id=native_ids)
def test_within_sport_duplicate_native_id_is_rejected(
    kind: str, sport: Sport, native_id: int
) -> None:
    """Two records of the same sport sharing a native id are rejected.

    Feature: mlb-support, Property 2
    Validates: Requirements 1.3
    """

    with fresh_session() as session:
        first = _make_entity(session, kind, sport, native_id, team_offset=1_000_000_000)
        second = _make_entity(session, kind, sport, native_id, team_offset=1_500_000_000)
        session.add_all([first, second])

        with pytest.raises(IntegrityError):
            session.commit()

        session.rollback()
