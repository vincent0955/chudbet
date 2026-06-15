"""Property-based test for nearest-half-point MLB prop lines.

Feature: mlb-support, Property 18
Validates: Requirements 9.2

Property 18 -- *Prop lines are the nearest half-point to the rolling average.*
For arbitrary player histories, every prop line offered by
``app.mlb.prop_lines.build_mlb_game_prop_lines_bundle`` must equal the half-point
value nearest to the rolling average of the player's per-game values for that
``MLBStatType`` over the prior MLB games inside the lookback window -- that is,
``round(avg - 0.5) + 0.5`` -- and must always have a fractional part of exactly
``0.5``.

The world generates rosters (pitchers and batters on both teams) plus a history
of prior MLB games, each carrying an explicit per-player box-score line. We
record the exact values we insert per ``(player, stat)`` so the expected line
can be recomputed independently of the service and compared against the bundle
output.
"""

from __future__ import annotations

from collections import defaultdict
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
from app.mlb.enums import MLBStatType
from app.mlb.prop_lines import build_mlb_game_prop_lines_bundle

# Target game date; every generated prior game is placed strictly before it and
# within the default prop lookback window (30 days) so all count as samples.
_TARGET_DATE = date(2024, 7, 20)

# Maps each offered stat type (by value) to the box-score column it reads.
_STAT_COLUMNS: dict[str, str] = {
    MLBStatType.HITS.value: "hits",
    MLBStatType.TOTAL_BASES.value: "total_bases",
    MLBStatType.RBI.value: "rbi",
    MLBStatType.RUNS.value: "runs",
    MLBStatType.STRIKEOUTS_PITCHER.value: "strikeouts_pitcher",
}


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


def _expected_half_point(values: list[int]) -> float:
    """Recompute the nearest-half-point line independently of the service."""
    avg = sum(values) / len(values)
    return float(round(avg - 0.5) + 0.5)


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
def test_property18_prop_lines_are_nearest_half_point(world: dict) -> None:
    """**Validates: Requirements 9.2**

    Feature: mlb-support, Property 18

    Build an MLB game with arbitrary player histories, price the player props,
    and assert every offered prop line equals ``round(avg - 0.5) + 0.5`` for the
    player's per-game average of that stat and always has a fractional part of
    exactly ``0.5``.
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

        # Box-score lines for every player in every prior game. Record the exact
        # per-(player, column) values so the expected line can be recomputed.
        recorded: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        pool_idx = 0
        stat_rows: list[MLBPlayerGameStat] = []
        for g in prior_games:
            for player in players:
                vals = [stat_pool[(pool_idx + k) % len(stat_pool)] for k in range(5)]
                pool_idx += 1
                columns = ("hits", "total_bases", "rbi", "runs", "strikeouts_pitcher")
                for column, value in zip(columns, vals):
                    recorded[player.id][column].append(value)
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

        # At least one player/line must be offered so the property is non-vacuous.
        offered_lines = 0
        for player_lines in bundle.players:
            for stat_line in player_lines.stat_lines:
                offered_lines += 1
                column = _STAT_COLUMNS[stat_line.stat_type]
                values = recorded[player_lines.id][column]
                expected = _expected_half_point(values)

                assert stat_line.line == expected, (
                    f"{player_lines.full_name}/{stat_line.stat_type}: line "
                    f"{stat_line.line!r} != nearest half-point {expected!r} "
                    f"(values={values})"
                )
                # Fractional part must be exactly 0.5 (admits no push).
                fractional = stat_line.line - int(stat_line.line)
                assert abs(fractional) == 0.5, (
                    f"{player_lines.full_name}/{stat_line.stat_type}: line "
                    f"{stat_line.line!r} fractional part {fractional!r} != 0.5"
                )

        assert offered_lines > 0, "expected at least one offered prop line"
    finally:
        gen.close()
