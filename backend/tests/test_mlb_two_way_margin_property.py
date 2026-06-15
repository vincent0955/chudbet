"""Property-based test for the two-way house margin on MLB markets.

Feature: mlb-support, Property 14
Validates: Requirements 8.5, 9.4

Property 14 -- *Two-way markets carry a positive house margin.* For an arbitrary
MLB game and arbitrary player histories, every two-way MLB market produced by
the pricers must carry an overround: the implied probabilities of its two sides,
converted back from the American odds the pricer emits, must sum to a value
strictly greater than ``1``.

The two-way markets covered here are, from
``app.mlb.game_markets.build_mlb_game_markets`` (Req 8.5):

- the **moneyline** (home / away),
- the **run line** (home / away spread), and
- the **total runs** market (over / under),

and from ``app.mlb.prop_lines.build_mlb_game_prop_lines_bundle`` (Req 9.4):

- every offered player-prop **over / under** pair.

Both pricers are exercised across worlds with sparse history (so the baseball
default projections are used) and rich history (so sample-derived projections
are used); the margin must hold either way.
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
from app.mlb.game_markets import build_mlb_game_markets
from app.mlb.prop_lines import build_mlb_game_prop_lines_bundle

# Target game date; all generated prior games are placed strictly before it and
# within the prop lookback window (30 days) so they count as samples.
_TARGET_DATE = date(2024, 7, 20)


def _fresh_session() -> Iterator[Session]:
    """Yield an isolated in-memory SQLite session per hypothesis example.

    A brand-new engine per example keeps each generated world independent so
    rows from one example never leak into the next.
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


def _implied_probability(american: str) -> float:
    """Convert an American-odds string back to its implied probability.

    For negative odds ``-O`` the implied probability is ``O / (O + 100)``; for
    positive odds ``+O`` it is ``100 / (O + 100)``. This is the inverse of the
    pricer's ``american_from_probability``.
    """
    odds = int(american)
    if odds < 0:
        magnitude = float(-odds)
        return magnitude / (magnitude + 100.0)
    return 100.0 / (float(odds) + 100.0)


# Strategies -----------------------------------------------------------------

# A world plan: a bag of prior (home_runs, away_runs) finals (0..12 games drives
# fallback vs sample-derived projections), per-team roster sizes (always at
# least one pitcher and one batter so both prop families are exercised), and a
# non-empty pool of non-negative stat values cycled through for box scores.
_world = st.fixed_dictionaries(
    {
        "prior_finals": st.lists(
            st.tuples(st.integers(min_value=0, max_value=18), st.integers(min_value=0, max_value=18)),
            min_size=0,
            max_size=12,
        ),
        "n_batters": st.integers(min_value=1, max_value=3),
        "n_pitchers": st.integers(min_value=1, max_value=2),
        "stat_pool": st.lists(st.integers(min_value=0, max_value=12), min_size=1, max_size=16),
    }
)


def _assert_two_way_overround(a_american: str, b_american: str, label: str) -> None:
    """Assert the two sides' implied probabilities sum to strictly > 1."""
    implied_sum = _implied_probability(a_american) + _implied_probability(b_american)
    assert implied_sum > 1.0, f"{label}: implied probabilities sum to {implied_sum!r}, expected > 1"


@settings(deadline=None, max_examples=150)
@given(world=_world)
def test_property14_two_way_markets_carry_positive_house_margin(world: dict) -> None:
    """**Validates: Requirements 8.5, 9.4**

    Feature: mlb-support, Property 14

    Build an arbitrary MLB game with arbitrary player histories, price its game
    markets and player props, and assert that every two-way market (moneyline,
    run line, total runs, and each offered over/under prop) has American odds
    whose implied probabilities sum to strictly more than 1.
    """
    prior_finals: list[tuple[int, int]] = world["prior_finals"]
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

        # Prior MLB games between the two teams, each with a final score, placed
        # on distinct days strictly before the target date and within 30 days.
        prior_games: list[Game] = []
        next_game_native = 700000
        for i, (home_runs, away_runs) in enumerate(prior_finals):
            g = Game(
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                game_date=_TARGET_DATE - timedelta(days=i + 1),
                status="Final",
                sport=Sport.MLB,
                mlb_game_id=str(next_game_native),
                home_score=home_runs,
                away_score=away_runs,
            )
            prior_games.append(g)
            next_game_native += 1
        session.add_all(prior_games)
        session.flush()

        # Box-score lines for every player in every prior game so players have
        # histories that drive prop lines. Stat values cycle through the pool.
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
        if stat_rows:
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

        # --- Game markets (Req 8.5): moneyline, run line, total runs ---
        markets = build_mlb_game_markets(session, target)
        _assert_two_way_overround(
            markets.moneyline.home_american, markets.moneyline.away_american, "moneyline"
        )
        _assert_two_way_overround(
            markets.spread.home_american, markets.spread.away_american, "run line"
        )
        _assert_two_way_overround(
            markets.total.over_american, markets.total.under_american, "total runs"
        )

        # --- Player props (Req 9.4): every offered over/under pair ---
        bundle = build_mlb_game_prop_lines_bundle(session, target)
        for player_lines in bundle.players:
            for stat_line in player_lines.stat_lines:
                _assert_two_way_overround(
                    stat_line.over_american,
                    stat_line.under_american,
                    f"prop {player_lines.full_name}/{stat_line.stat_type}",
                )
    finally:
        gen.close()
