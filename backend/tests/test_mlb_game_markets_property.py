"""Property-based test for MLB game-market structure.

Exercises ``app.mlb.game_markets.build_mlb_game_markets`` against arbitrary MLB
games and prior run-total histories seeded into an isolated in-memory SQLite
database. The structural shape of the produced markets must hold for every
generated world, independent of the underlying projections:

- a moneyline with an American price for the home side and the away side
  (Req 8.1);
- a run line whose home and away lines are equal in magnitude, opposite in
  sign, and expressed as half-run values, each priced (Req 8.2);
- a total runs market with a single positive half-run line and an over price
  and an under price (Req 8.3).

Feature: mlb-support, Property 13
Validates: Requirements 8.1, 8.2, 8.3
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Importing the models package registers every table on ``Base.metadata``.
import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.enums import Sport
from app.db.models import Game, Team
from app.mlb.game_markets import MLB_RUN_LINE, build_mlb_game_markets

# American-odds strings look like ``+150`` or ``-200`` (sign required).
_AMERICAN_RE = re.compile(r"^[+-]\d+$")

_TARGET_DATE = date(2026, 6, 15)


def _fresh_session() -> Iterator[Session]:
    """Yield an isolated in-memory SQLite session per hypothesis example.

    A brand-new engine per example keeps each generated world fully independent
    so seeded games never leak across examples.
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


def _is_american_odds(value: str) -> bool:
    """A valid American-odds string carries a sign and a magnitude >= 100."""
    if not isinstance(value, str) or not _AMERICAN_RE.match(value):
        return False
    return abs(int(value)) >= 100


def _is_half_run(value: float) -> bool:
    """A half-run line has a fractional part of exactly 0.5."""
    return math.isclose(value - math.floor(value), 0.5, abs_tol=1e-9)


# Strategies -----------------------------------------------------------------

# A bag of (runs_for, runs_against) results for a team's prior games. An empty
# list exercises the sparse-history default branch; longer lists exercise the
# computed-projection branch and the lookback window.
_history = st.lists(
    st.tuples(st.integers(min_value=0, max_value=22), st.integers(min_value=0, max_value=22)),
    min_size=0,
    max_size=14,
)

_world = st.fixed_dictionaries({"home_history": _history, "away_history": _history})


@settings(deadline=None, max_examples=150)
@given(world=_world)
def test_property13_mlb_game_markets_have_required_structure(world: dict) -> None:
    """**Validates: Requirements 8.1, 8.2, 8.3**

    Feature: mlb-support, Property 13

    For an arbitrary MLB game with arbitrary prior run-total histories for both
    teams, ``build_mlb_game_markets`` produces a moneyline, a run line, and a
    total runs market whose structure satisfies the required shape.
    """
    gen = _fresh_session()
    session = next(gen)
    try:
        home_history: list[tuple[int, int]] = world["home_history"]
        away_history: list[tuple[int, int]] = world["away_history"]

        # Monotonic counters keep sport-native ids unique within the world.
        next_team_id = 1
        next_game_id = 1

        def _new_team(label: str) -> Team:
            nonlocal next_team_id
            tid = next_team_id
            next_team_id += 1
            team = Team(
                name=f"MLB {label} {tid}",
                sport=Sport.MLB,
                mlb_team_id=tid,
                abbreviation=f"M{tid % 100:02d}",
            )
            session.add(team)
            session.flush()
            return team

        home_team = _new_team("Home")
        away_team = _new_team("Away")

        def _seed_history(team: Team, history: list[tuple[int, int]]) -> None:
            """Seed final prior MLB games (team as home) before the target date."""
            nonlocal next_game_id
            for offset, (runs_for, runs_against) in enumerate(history, start=1):
                opponent = _new_team("Opp")
                gid = next_game_id
                next_game_id += 1
                session.add(
                    Game(
                        home_team_id=team.id,
                        away_team_id=opponent.id,
                        game_date=_TARGET_DATE - timedelta(days=offset),
                        status="Final",
                        sport=Sport.MLB,
                        mlb_game_id=str(gid),
                        home_score=runs_for,
                        away_score=runs_against,
                    )
                )
            session.flush()

        _seed_history(home_team, home_history)
        _seed_history(away_team, away_history)

        # The target game: no scores yet, scheduled on the target date.
        target_gid = next_game_id
        next_game_id += 1
        target = Game(
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            game_date=_TARGET_DATE,
            status="Scheduled",
            sport=Sport.MLB,
            mlb_game_id=str(target_gid),
        )
        session.add(target)
        session.flush()
        session.commit()

        markets = build_mlb_game_markets(session, target)

        # Req 8.1: moneyline has exactly a home and an away American price.
        assert _is_american_odds(markets.moneyline.home_american)
        assert _is_american_odds(markets.moneyline.away_american)

        # Req 8.2: run line — equal magnitude, opposite sign, half-run, priced.
        home_line = markets.spread.home_line
        away_line = markets.spread.away_line
        assert math.isclose(home_line, -away_line, abs_tol=1e-9)
        assert math.isclose(abs(home_line), abs(away_line), abs_tol=1e-9)
        assert home_line != 0.0
        assert math.isclose(abs(home_line), MLB_RUN_LINE, abs_tol=1e-9)
        assert _is_half_run(abs(home_line))
        assert _is_american_odds(markets.spread.home_american)
        assert _is_american_odds(markets.spread.away_american)

        # Req 8.3: total runs — single positive half-run line, over/under priced.
        total_line = markets.total.line
        assert total_line > 0.0
        assert _is_half_run(total_line)
        assert _is_american_odds(markets.total.over_american)
        assert _is_american_odds(markets.total.under_american)
    finally:
        gen.close()
