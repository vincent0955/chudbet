"""Property-based test for MLB prop milestone lines.

Feature: mlb-support, Property 18
Validates: Requirements 9.2

Property 18 -- *Prop milestones are the fixed ``1+``/``2+``/``3+`` ladder at
half-point lines.* For arbitrary player histories, every stat line offered by
``app.mlb.prop_lines.build_mlb_game_prop_lines_bundle`` must expose exactly the
thresholds ``1``, ``2``, ``3`` (in order), each stored at the half-point line
``threshold - 0.5`` (``0.5``/``1.5``/``2.5``) so it admits no push and grades as
``value >= threshold`` under the existing OVER settlement.

The world generates rosters (pitchers and batters on both teams) plus a history
of prior MLB games carrying explicit per-player box-score lines, large enough to
clear the minimum sample size so milestones are actually offered.
"""

from __future__ import annotations

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
from app.mlb.prop_lines import build_mlb_game_prop_lines_bundle

# Target game date; every generated prior game is placed strictly before it and
# within the default prop lookback window (30 days) so all count as samples.
_TARGET_DATE = date(2024, 7, 20)


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


# A world plan: enough prior games to clear the default min-sample size (5), per
# team roster sizes (always at least one pitcher and one batter so both prop
# families are exercised), and a non-empty pool of non-negative stat values
# cycled through to fill the box scores.
_world = st.fixed_dictionaries(
    {
        "n_games": st.integers(min_value=5, max_value=12),
        "n_batters": st.integers(min_value=1, max_value=3),
        "n_pitchers": st.integers(min_value=1, max_value=2),
        "stat_pool": st.lists(
            st.integers(min_value=0, max_value=15), min_size=1, max_size=20
        ),
    }
)


@settings(deadline=None, max_examples=150)
@given(world=_world)
def test_property18_prop_milestones_are_fixed_half_point_ladder(world: dict) -> None:
    """**Validates: Requirements 9.2**

    Feature: mlb-support, Property 18

    Build an MLB game with arbitrary player histories, price the player props,
    and assert every offered stat line exposes exactly the ``1+``/``2+``/``3+``
    milestones at half-point lines ``0.5``/``1.5``/``2.5`` (fractional part
    exactly ``0.5``).
    """
    n_games: int = world["n_games"]
    n_batters: int = world["n_batters"]
    n_pitchers: int = world["n_pitchers"]
    stat_pool: list[int] = world["stat_pool"]

    gen = _fresh_session()
    session = next(gen)
    try:
        # Two MLB teams.
        home_team = Team(name="Home Nine", sport=Sport.MLB, mlb_team_id=147, abbreviation="HOM")
        away_team = Team(name="Away Nine", sport=Sport.MLB, mlb_team_id=111, abbreviation="AWY")
        session.add_all([home_team, away_team])
        session.flush()

        # Rosters: pitchers + batters on each team.
        players: list[Player] = []
        next_player_id = 1000
        for team in (home_team, away_team):
            for _ in range(n_pitchers):
                players.append(
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
                players.append(
                    Player(
                        full_name=f"Batter {next_player_id}",
                        team_id=team.id,
                        sport=Sport.MLB,
                        mlb_player_id=next_player_id,
                        primary_position="CF",
                    )
                )
                next_player_id += 1
        session.add_all(players)
        session.flush()

        # Prior MLB games between the two teams on distinct days strictly before
        # the target date and inside the 30-day lookback window.
        prior_games: list[Game] = []
        next_game_native = 700000
        for i in range(n_games):
            g = Game(
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                game_date=_TARGET_DATE - timedelta(days=i + 1),
                status="Final",
                sport=Sport.MLB,
                mlb_game_id=str(next_game_native),
                home_score=i % 7,
                away_score=(i + 3) % 7,
            )
            prior_games.append(g)
            next_game_native += 1
        session.add_all(prior_games)
        session.flush()

        # Box-score lines for every player in every prior game.
        pool_idx = 0
        stat_rows: list[MLBPlayerGameStat] = []
        for g in prior_games:
            for player in players:
                vals = [stat_pool[(pool_idx + k) % len(stat_pool)] for k in range(5)]
                pool_idx += 1
                stat_rows.append(
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
        session.add_all(stat_rows)
        session.flush()

        # The target (unplayed) game being priced.
        target = Game(
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            game_date=_TARGET_DATE,
            status="Scheduled",
            sport=Sport.MLB,
            mlb_game_id=str(next_game_native),
        )
        session.add(target)
        session.flush()

        bundle = build_mlb_game_prop_lines_bundle(session, target)

        # At least one stat line must be offered so the property is non-vacuous.
        offered_lines = 0
        for player_lines in bundle.players:
            for stat_line in player_lines.stat_lines:
                offered_lines += 1

                # Exactly the fixed 1+/2+/3+ ladder, in order.
                assert [t.threshold for t in stat_line.thresholds] == [1, 2, 3], (
                    f"{player_lines.full_name}/{stat_line.stat_type}: thresholds "
                    f"{[t.threshold for t in stat_line.thresholds]!r} != [1, 2, 3]"
                )

                for milestone in stat_line.thresholds:
                    # Each milestone's line is threshold - 0.5 ...
                    assert milestone.line == milestone.threshold - 0.5, (
                        f"{player_lines.full_name}/{stat_line.stat_type}: "
                        f"{milestone.threshold}+ line {milestone.line!r} "
                        f"!= {milestone.threshold - 0.5!r}"
                    )
                    # ... and therefore always has a fractional part of exactly 0.5.
                    fractional = milestone.line - int(milestone.line)
                    assert abs(fractional) == 0.5, (
                        f"{player_lines.full_name}/{stat_line.stat_type}: line "
                        f"{milestone.line!r} fractional part {fractional!r} != 0.5"
                    )

        assert offered_lines > 0, "expected at least one offered prop line"
    finally:
        gen.close()
