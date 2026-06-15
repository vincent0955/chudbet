"""Property-based and example tests for sport persistence validity.

Exercises the shared ``sport`` discriminator and the sport/native-id CHECK
constraints on the ``teams``, ``players``, and ``games`` tables, plus the
isolated ``mlb_player_game_stats`` table. Every persisted domain record must be
associated with exactly one valid sport drawn from the enumerated set
``{NBA, MLB}`` (Req 1.1), and a record submitted with a missing or
out-of-vocabulary sport must be rejected with no partial persistence (Req 1.2).

Feature: mlb-support, Property 1
Validates: Requirements 1.1, 1.2
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker

# Importing the models package registers every table on ``Base.metadata``.
import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.enums import Sport
from app.db.models import Game, MLBPlayerGameStat, Player, Team

# The complete, enumerated vocabulary of valid sports (Req 1.1).
_VALID_SPORTS: frozenset[Sport] = frozenset(Sport)

# Errors raised by the persistence layer when an invalid/missing sport is
# rejected. A CHECK / NOT NULL violation surfaces as IntegrityError; an enum
# coercion failure can surface as StatementError/DBAPIError depending on layer.
_REJECTION_ERRORS = (IntegrityError, StatementError, DBAPIError)


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


def _make_team(sport: Sport, native_id: int) -> Team:
    """Build a team obeying the sport/native-id invariant (Req 1.1/1.3)."""
    if sport is Sport.NBA:
        return Team(name=f"NBA Team {native_id}", sport=Sport.NBA, nba_team_id=native_id)
    return Team(
        name=f"MLB Team {native_id}",
        sport=Sport.MLB,
        mlb_team_id=native_id,
        abbreviation=f"M{native_id % 100:02d}",
    )


def _make_player(sport: Sport, native_id: int, team_id: int) -> Player:
    if sport is Sport.NBA:
        return Player(
            full_name=f"NBA Player {native_id}",
            team_id=team_id,
            sport=Sport.NBA,
            nba_player_id=native_id,
        )
    return Player(
        full_name=f"MLB Player {native_id}",
        team_id=team_id,
        sport=Sport.MLB,
        mlb_player_id=native_id,
        primary_position="P" if native_id % 2 == 0 else "OF",
    )


def _make_game(sport: Sport, native_id: int, home_id: int, away_id: int) -> Game:
    if sport is Sport.NBA:
        return Game(
            home_team_id=home_id,
            away_team_id=away_id,
            game_date=date(2026, 4, 1),
            status="Scheduled",
            sport=Sport.NBA,
            nba_game_id=str(native_id),
        )
    return Game(
        home_team_id=home_id,
        away_team_id=away_id,
        game_date=date(2026, 4, 1),
        status="Scheduled",
        sport=Sport.MLB,
        mlb_game_id=str(native_id),
    )


# Strategies -----------------------------------------------------------------

_sports = st.sampled_from([Sport.NBA, Sport.MLB])

# A "world plan": a list of team sports (drives how many teams of each sport
# exist) plus a small bag of non-negative stat values for any MLB box score.
_world = st.fixed_dictionaries(
    {
        "team_sports": st.lists(_sports, min_size=1, max_size=6),
        "stat_values": st.lists(st.integers(min_value=0, max_value=60), min_size=5, max_size=5),
    }
)

# Sport tokens that are NOT in the enumerated vocabulary {NBA, MLB}. Includes
# wrong-case variants to assert the discriminator is case-sensitive.
_invalid_sport_tokens = st.sampled_from(
    ["NFL", "nba", "mlb", "Nba", "BASEBALL", "", " ", "NBA ", "XYZ", "soccer"]
)


# Property 1 (Req 1.1): every persisted record has exactly one valid sport ----


@settings(deadline=None, max_examples=150)
@given(world=_world)
def test_property1_persisted_records_have_exactly_one_valid_sport(world: dict) -> None:
    """**Validates: Requirements 1.1**

    Feature: mlb-support, Property 1

    Build an arbitrary world of teams (each NBA or MLB), one player per team,
    a same-sport game wherever a sport has two or more teams, and an MLB box
    score line for an MLB game. Every row that lands in the database must carry
    exactly one sport value, and that value must be a member of the enumerated
    set {NBA, MLB}. The isolated MLB stat line, which has no sport column of its
    own, must reference a game and player that are both MLB.
    """
    gen = _fresh_session()
    session = next(gen)
    try:
        team_sports: list[Sport] = world["team_sports"]
        stat_values: list[int] = world["stat_values"]

        # Per-sport monotonic counters guarantee unique native ids within a
        # sport so the per-sport unique indexes are never violated.
        next_id = {Sport.NBA: 1, Sport.MLB: 1}
        teams_by_sport: dict[Sport, list[Team]] = {Sport.NBA: [], Sport.MLB: []}

        for sport in team_sports:
            tid = next_id[sport]
            next_id[sport] += 1
            team = _make_team(sport, tid)
            session.add(team)
            session.flush()
            teams_by_sport[sport].append(team)

            player = _make_player(sport, tid, team.id)
            session.add(player)
            session.flush()

        # One same-sport game per sport that has at least two teams.
        games_by_sport: dict[Sport, Game | None] = {Sport.NBA: None, Sport.MLB: None}
        for sport, teams in teams_by_sport.items():
            if len(teams) >= 2:
                gid = next_id[sport]
                next_id[sport] += 1
                game = _make_game(sport, gid, teams[0].id, teams[1].id)
                session.add(game)
                session.flush()
                games_by_sport[sport] = game

        # An MLB box-score line for the MLB game, if one exists. Its "sport" is
        # implied by the MLB game/player it references (isolated table).
        mlb_game = games_by_sport[Sport.MLB]
        mlb_stat: MLBPlayerGameStat | None = None
        if mlb_game is not None:
            mlb_player = teams_by_sport[Sport.MLB][0].players[0]
            mlb_stat = MLBPlayerGameStat(
                player_id=mlb_player.id,
                game_id=mlb_game.id,
                hits=stat_values[0],
                total_bases=stat_values[1],
                rbi=stat_values[2],
                runs=stat_values[3],
                strikeouts_pitcher=stat_values[4],
            )
            session.add(mlb_stat)
            session.flush()

        session.commit()

        # Every persisted team/player/game carries exactly one valid sport.
        for row in session.scalars(select(Team)).all():
            assert row.sport in _VALID_SPORTS
        for row in session.scalars(select(Player)).all():
            assert row.sport in _VALID_SPORTS
        for game in session.scalars(select(Game)).all():
            assert game.sport in _VALID_SPORTS

        # The isolated MLB stat line resolves to exactly the MLB sport via both
        # its player and its game.
        for stat in session.scalars(select(MLBPlayerGameStat)).all():
            linked_game = session.get(Game, stat.game_id)
            linked_player = session.get(Player, stat.player_id)
            assert linked_game.sport is Sport.MLB
            assert linked_player.sport is Sport.MLB
    finally:
        gen.close()


# Property 1 (Req 1.2): out-of-vocabulary sport rejected, no partial persistence


@settings(deadline=None, max_examples=150)
@given(
    bad_sport=_invalid_sport_tokens,
    native_id=st.integers(min_value=1, max_value=10_000),
)
def test_property1_invalid_sport_is_rejected_without_partial_persistence(
    bad_sport: str, native_id: int
) -> None:
    """**Validates: Requirements 1.2**

    Feature: mlb-support, Property 1

    A team submitted with a sport outside the enumerated set {NBA, MLB} is
    rejected by the persistence layer (the sport/native-id CHECK constraint),
    and nothing is partially persisted: an already-committed valid record
    remains the only row, and the rejected record is absent. The failed
    transaction rolls back so subsequent valid writes still succeed.
    """
    gen = _fresh_session()
    session = next(gen)
    try:
        # Seed one valid, committed team so we can prove the rejected insert
        # leaves prior state intact and adds nothing.
        valid = _make_team(Sport.NBA, native_id)
        session.add(valid)
        session.commit()
        assert session.scalar(select(func.count()).select_from(Team)) == 1

        # Submit a team carrying an out-of-vocabulary sport. It still supplies a
        # native id, so the only thing wrong is the sport vocabulary itself.
        bad = Team(name="Rogue", sport=bad_sport, nba_team_id=native_id + 1)
        session.add(bad)

        with pytest.raises(_REJECTION_ERRORS):
            session.commit()
        session.rollback()

        # No partial persistence: still exactly the one valid row, and the
        # rogue row never landed.
        assert session.scalar(select(func.count()).select_from(Team)) == 1
        assert (
            session.scalar(select(func.count()).select_from(Team).where(Team.name == "Rogue")) == 0
        )

        # The session remains usable for valid writes after the rejection.
        another = _make_team(Sport.MLB, native_id)
        session.add(another)
        session.commit()
        assert session.scalar(select(func.count()).select_from(Team)) == 2
    finally:
        gen.close()


# Property 1 (Req 1.2 + 1.7): a missing sport never persists as NULL ----------


@settings(deadline=None, max_examples=100)
@given(native_id=st.integers(min_value=1, max_value=10_000))
def test_property1_missing_sport_never_persists_as_null(native_id: int) -> None:
    """**Validates: Requirements 1.2**

    Feature: mlb-support, Property 1

    A record may never be persisted with a NULL (absent) sport. An explicit
    NULL sport is rejected by the NOT NULL guard with no partial persistence,
    while an omitted sport is filled in with the default ``NBA`` (Req 1.7) so
    the persisted row still carries exactly one valid sport. Either way, no row
    with a missing sport ever lands.
    """
    gen = _fresh_session()
    session = next(gen)
    try:
        # An explicit NULL sport (bypassing the ORM default) is rejected.
        with pytest.raises(_REJECTION_ERRORS):
            session.execute(
                text("INSERT INTO teams (name, sport, nba_team_id) VALUES (:n, NULL, :i)"),
                {"n": "null-sport", "i": native_id},
            )
            session.commit()
        session.rollback()
        assert session.scalar(select(func.count()).select_from(Team)) == 0

        # An omitted sport defaults to the valid NBA discriminator (Req 1.7).
        team = Team(name="defaulted", nba_team_id=native_id)
        session.add(team)
        session.commit()
        session.refresh(team)
        assert team.sport is Sport.NBA
        assert team.sport in _VALID_SPORTS

        # No persisted row has a NULL sport.
        assert session.scalar(select(func.count()).select_from(Team).where(Team.sport.is_(None))) == 0
    finally:
        gen.close()
