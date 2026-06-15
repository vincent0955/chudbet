"""Property-based test for sparse-history fallback to configured defaults.

Feature: mlb-support, Property 16
Validates: Requirements 8.6, 9.3

Property 16 -- *Sparse history falls back to configured defaults.* When a team
has fewer prior MLB games than the configured minimum sample size, the
``MLB_Game_Market_Pricer`` must price every market from the configured baseball
default projections rather than the (insufficient) sample -- so the produced
markets are independent of whatever sparse history happens to exist, and the
total runs line equals the configured baseball default total (Req 8.6). In the
same regime, when a player has fewer prior MLB games than the configured prop
minimum sample size, the ``MLB_Prop_Line_Service`` must omit every applicable
stat line for that player and emit no over/under odds for it (Req 9.3).

The test seeds an isolated in-memory SQLite database per example. Every world
seeds strictly fewer prior games than both the game-market minimum and the prop
minimum, so both fallback regimes are exercised together:

- the sparse-history game markets must equal a zero-history *baseline* priced in
  the same session (proving the sparse sample is ignored), and the total line
  must equal ``MLB_DEFAULT_TOTAL`` with the run line at the default
  ``MLB_RUN_LINE`` magnitude (Req 8.6);
- every player's prop bundle must carry no stat lines at all (Req 9.3).
"""

from __future__ import annotations

import math
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
from app.db.models import Game, MLBPlayerGameStat, Player, Team
from app.mlb.config import get_game_min_samples, get_prop_min_samples
from app.mlb.game_markets import (
    MLB_DEFAULT_TOTAL,
    MLB_MIN_SAMPLE,
    MLB_RUN_LINE,
    build_mlb_game_markets,
)
from app.mlb.prop_lines import build_mlb_game_prop_lines_bundle

_TARGET_DATE = date(2025, 6, 15)

# The largest prior-game count that is strictly below BOTH configured minimums,
# so a single seeded count guarantees the game-market fallback (Req 8.6) and the
# prop omission (Req 9.3) at once. Never negative even if a minimum is 0/1.
_GAME_MIN = MLB_MIN_SAMPLE
_PROP_MIN = get_prop_min_samples()
_K_MAX = max(0, min(_GAME_MIN, _PROP_MIN) - 1)


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


def _is_half_run(value: float) -> bool:
    """A half-run line has a fractional part of exactly 0.5."""
    return math.isclose(value - math.floor(value), 0.5, abs_tol=1e-9)


# Strategies -----------------------------------------------------------------

# A world plan: how many prior finals to seed between the two teams (always
# strictly below both configured minimums), the per-team roster makeup (at least
# one pitcher and one batter so both prop families are exercised), and a
# non-empty pool of non-negative stat values cycled through the box scores.
_world = st.fixed_dictionaries(
    {
        "num_prior": st.integers(min_value=0, max_value=_K_MAX),
        "n_batters": st.integers(min_value=1, max_value=3),
        "n_pitchers": st.integers(min_value=1, max_value=2),
        "prior_scores": st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=18),
                st.integers(min_value=0, max_value=18),
            ),
            min_size=_K_MAX,
            max_size=_K_MAX,
        ),
        "stat_pool": st.lists(
            st.integers(min_value=0, max_value=12), min_size=1, max_size=16
        ),
    }
)


@settings(deadline=None, max_examples=150)
@given(world=_world)
def test_property16_sparse_history_falls_back_to_defaults(world: dict) -> None:
    """**Validates: Requirements 8.6, 9.3**

    Feature: mlb-support, Property 16

    With fewer prior MLB games than the configured minimums, MLB game markets
    are priced from the baseball defaults (total == ``MLB_DEFAULT_TOTAL``, run
    line at the default magnitude, and identical to a zero-history baseline),
    and every player's prop lines for under-sampled stats are omitted with no
    odds.
    """
    num_prior: int = world["num_prior"]
    n_batters: int = world["n_batters"]
    n_pitchers: int = world["n_pitchers"]
    prior_scores: list[tuple[int, int]] = world["prior_scores"]
    stat_pool: list[int] = world["stat_pool"]

    gen = _fresh_session()
    session = next(gen)
    try:
        next_team_id = 1
        next_player_id = 1
        next_game_native = 1

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

        def _roster(team: Team) -> list[Player]:
            nonlocal next_player_id
            built: list[Player] = []
            for _ in range(n_pitchers):
                built.append(
                    Player(
                        full_name=f"Pitcher {next_player_id}",
                        team_id=team.id,
                        sport=Sport.MLB,
                        mlb_player_id=next_player_id,
                        primary_position="P",
                    )
                )
                next_player_id += 1
            for _ in range(n_batters):
                built.append(
                    Player(
                        full_name=f"Batter {next_player_id}",
                        team_id=team.id,
                        sport=Sport.MLB,
                        mlb_player_id=next_player_id,
                        primary_position="CF",
                    )
                )
                next_player_id += 1
            session.add_all(built)
            session.flush()
            return built

        def _target_game(home: Team, away: Team) -> Game:
            nonlocal next_game_native
            gid = next_game_native
            next_game_native += 1
            g = Game(
                home_team_id=home.id,
                away_team_id=away.id,
                game_date=_TARGET_DATE,
                status="Scheduled",
                sport=Sport.MLB,
                mlb_game_id=str(gid),
            )
            session.add(g)
            session.flush()
            return g

        # --- Baseline: a target game whose teams have NO prior MLB history. ---
        base_home = _new_team("BaseHome")
        base_away = _new_team("BaseAway")
        baseline_target = _target_game(base_home, base_away)

        # --- Sparse: a target game whose teams share `num_prior` prior finals
        # (strictly below the configured minimums) plus rostered players whose
        # box-score history is likewise below the prop minimum. ---
        sparse_home = _new_team("Home")
        sparse_away = _new_team("Away")
        players = _roster(sparse_home) + _roster(sparse_away)

        prior_games: list[Game] = []
        for i in range(num_prior):
            home_runs, away_runs = prior_scores[i]
            gid = next_game_native
            next_game_native += 1
            g = Game(
                home_team_id=sparse_home.id,
                away_team_id=sparse_away.id,
                game_date=_TARGET_DATE - timedelta(days=i + 1),
                status="Final",
                sport=Sport.MLB,
                mlb_game_id=str(gid),
                home_score=home_runs,
                away_score=away_runs,
            )
            session.add(g)
            prior_games.append(g)
        session.flush()

        # Box scores for every player in every prior game so each player has a
        # (still under-sampled) history.
        pool_idx = 0
        for g in prior_games:
            for player in players:
                vals = [stat_pool[(pool_idx + k) % len(stat_pool)] for k in range(5)]
                pool_idx += 1
                session.add(
                    MLBPlayerGameStat(
                        player_id=player.id,
                        game_id=g.id,
                        hits=vals[0],
                        total_bases=vals[1],
                        rbi=vals[2],
                        runs=vals[3],
                        strikeouts_pitcher=vals[4],
                    )
                )
        session.flush()

        sparse_target = _target_game(sparse_home, sparse_away)
        session.commit()

        # --- Game markets (Req 8.6) ---
        baseline = build_mlb_game_markets(session, baseline_target)
        sparse = build_mlb_game_markets(session, sparse_target)

        # The sparse sample is below the minimum, so the markets must match the
        # zero-history baseline exactly: the sparse history is ignored.
        assert sparse.sample_games_home < MLB_MIN_SAMPLE
        assert sparse.sample_games_away < MLB_MIN_SAMPLE

        assert sparse.moneyline.home_american == baseline.moneyline.home_american
        assert sparse.moneyline.away_american == baseline.moneyline.away_american
        assert math.isclose(sparse.spread.home_line, baseline.spread.home_line, abs_tol=1e-9)
        assert math.isclose(sparse.spread.away_line, baseline.spread.away_line, abs_tol=1e-9)
        assert sparse.spread.home_american == baseline.spread.home_american
        assert sparse.spread.away_american == baseline.spread.away_american
        assert math.isclose(sparse.total.line, baseline.total.line, abs_tol=1e-9)
        assert sparse.total.over_american == baseline.total.over_american
        assert sparse.total.under_american == baseline.total.under_american

        # The configured baseball default total drives the total runs line, and
        # the run line uses the default half-run magnitude (Req 8.6).
        assert math.isclose(sparse.total.line, MLB_DEFAULT_TOTAL, abs_tol=1e-9)
        assert math.isclose(abs(sparse.spread.home_line), MLB_RUN_LINE, abs_tol=1e-9)
        assert _is_half_run(sparse.total.line)
        assert _is_half_run(abs(sparse.spread.home_line))

        # --- Player props (Req 9.3) ---
        bundle = build_mlb_game_prop_lines_bundle(session, sparse_target)
        prop_min = get_prop_min_samples()
        assert bundle.players, "expected rostered players in the prop bundle"
        for player_lines in bundle.players:
            # Every player is below the prop minimum sample size, so no stat
            # line (and therefore no over/under odds) is offered.
            assert player_lines.sample_size < prop_min
            assert player_lines.stat_lines == []
    finally:
        gen.close()
