"""Property-based test for MLB pricing sample exclusion.

Feature: mlb-support, Property 15
Validates: Requirements 8.4, 9.5

Property 15 -- *Pricing samples exclude the target game and other sports.* The
MLB game-market pricer (``app.mlb.game_markets.build_mlb_game_markets``) and the
MLB prop-line service (``app.mlb.prop_lines.build_mlb_game_prop_lines_bundle``)
derive their projections **only** from prior MLB games, explicitly excluding the
target game itself (Req 8.4, 9.5) and scoped to ``sport == MLB`` (Req 8.4).

This test pins that behavior down as an invariance property: for an arbitrary
MLB world, the markets and prop lines produced for a target game must be
**byte-for-byte identical** whether or not the database additionally contains

- the target game's own (later) results -- its final run totals and a box-score
  line for every roster player (the "exclude the target game" clause), and
- foreign-sport noise -- NBA games, NBA players, and NBA player stats, including
  an NBA game that points at the very same internal team rows as the MLB target
  game (so only the ``sport == MLB`` scope -- not a team-id mismatch -- can keep
  it out of the sample), plus an MLB-shaped stat line attached to an NBA game
  (so only the ``sport == MLB`` join scope can keep it out of the prop sample).

If either pricer leaked any of that data into its sample, the resulting lines or
odds would change and the equality assertion would fail.
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
from app.db.models import Game, MLBPlayerGameStat, Player, PlayerGameStat, Team
from app.mlb.game_markets import build_mlb_game_markets
from app.mlb.prop_lines import build_mlb_game_prop_lines_bundle

# Target game date; all prior MLB games are placed strictly before it and within
# the prop lookback window (30 days) so they count as samples.
_TARGET_DATE = date(2025, 7, 20)

# An obviously out-of-distribution value used for every noise stat/score so that,
# were the noise ever included in a sample, it would shift the produced numbers.
_NOISE = 999


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


def _market_fingerprint(markets) -> dict:
    """Pricing-relevant fields of the markets (excludes the ``game`` echo).

    The target game's ``GameRead`` echo legitimately changes once we add its
    results, so it is excluded; only the projected lines, prices, and sample
    counts are compared.
    """
    return {
        "lookback": markets.lookback,
        "sample_games_home": markets.sample_games_home,
        "sample_games_away": markets.sample_games_away,
        "moneyline": markets.moneyline.model_dump(),
        "spread": markets.spread.model_dump(),
        "total": markets.total.model_dump(),
    }


def _props_fingerprint(bundle) -> dict:
    """Pricing-relevant fields of the prop bundle (excludes the ``game`` echo)."""
    return {
        "lookback_days": bundle.lookback_days,
        "min_samples": bundle.min_samples,
        "players": [p.model_dump() for p in bundle.players],
    }


# Strategies -----------------------------------------------------------------

# A world plan: prior MLB finals between the two teams (>= 5 so prop lines are
# actually offered for the default min-sample of 5), roster composition, and a
# pool of non-negative box-score values cycled through the prior games.
_world = st.fixed_dictionaries(
    {
        "prior_finals": st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=15),
                st.integers(min_value=0, max_value=15),
            ),
            min_size=5,
            max_size=12,
        ),
        "n_batters": st.integers(min_value=1, max_value=2),
        "n_pitchers": st.integers(min_value=1, max_value=1),
        "stat_pool": st.lists(st.integers(min_value=0, max_value=10), min_size=1, max_size=12),
    }
)


@settings(deadline=None, max_examples=120)
@given(world=_world)
def test_property15_pricing_samples_exclude_target_game_and_other_sports(world: dict) -> None:
    """**Validates: Requirements 8.4, 9.5**

    Feature: mlb-support, Property 15

    Price an arbitrary MLB game's markets and props from a clean MLB-only world,
    then add (a) the target game's own results plus a box line for every player,
    and (b) NBA games/players/stats -- including an NBA game over the same team
    rows and an MLB-shaped stat line on an NBA game. Re-pricing must reproduce
    the original markets and prop lines exactly.
    """
    prior_finals: list[tuple[int, int]] = world["prior_finals"]
    n_batters: int = world["n_batters"]
    n_pitchers: int = world["n_pitchers"]
    stat_pool: list[int] = world["stat_pool"]

    gen = _fresh_session()
    session = next(gen)
    try:
        # --- Two MLB teams ---
        home_team = Team(name="Home Nine", sport=Sport.MLB, mlb_team_id=147, abbreviation="HOM")
        away_team = Team(name="Away Nine", sport=Sport.MLB, mlb_team_id=111, abbreviation="AWY")
        session.add_all([home_team, away_team])
        session.flush()

        # --- MLB rosters: pitchers + batters on each team ---
        mlb_players: list[Player] = []
        next_player_native = 5000
        for team in (home_team, away_team):
            for _ in range(n_pitchers):
                mlb_players.append(
                    Player(
                        full_name=f"Pitcher {next_player_native}",
                        team_id=team.id,
                        sport=Sport.MLB,
                        mlb_player_id=next_player_native,
                        primary_position="P",
                    )
                )
                next_player_native += 1
            for _ in range(n_batters):
                mlb_players.append(
                    Player(
                        full_name=f"Batter {next_player_native}",
                        team_id=team.id,
                        sport=Sport.MLB,
                        mlb_player_id=next_player_native,
                        primary_position="CF",
                    )
                )
                next_player_native += 1
        session.add_all(mlb_players)
        session.flush()

        # --- Prior MLB finals between the two teams, on distinct days inside the
        #     30-day prop window, each with a box line for every MLB player ---
        next_game_native = 800000
        pool_idx = 0
        for i, (home_runs, away_runs) in enumerate(prior_finals):
            prior = Game(
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                game_date=_TARGET_DATE - timedelta(days=i + 1),
                status="Final",
                sport=Sport.MLB,
                mlb_game_id=str(next_game_native),
                home_score=home_runs,
                away_score=away_runs,
            )
            next_game_native += 1
            session.add(prior)
            session.flush()
            for player in mlb_players:
                vals = [stat_pool[(pool_idx + k) % len(stat_pool)] for k in range(5)]
                pool_idx += 1
                session.add(
                    MLBPlayerGameStat(
                        player_id=player.id,
                        game_id=prior.id,
                        hits=vals[0],
                        total_bases=vals[1],
                        rbi=vals[2],
                        runs=vals[3],
                        strikeouts_pitcher=vals[4],
                    )
                )
        session.flush()

        # --- The target (unplayed) game being priced ---
        target = Game(
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            game_date=_TARGET_DATE,
            status="Scheduled",
            sport=Sport.MLB,
            mlb_game_id=str(next_game_native),
        )
        next_game_native += 1
        session.add(target)
        session.flush()
        session.commit()

        # --- Baseline: price from the clean MLB-only world ---
        baseline_markets = _market_fingerprint(build_mlb_game_markets(session, target))
        baseline_props = _props_fingerprint(build_mlb_game_prop_lines_bundle(session, target))

        # === Add noise that MUST NOT influence the pricing ====================

        # (a) The target game's OWN results plus a box line for every player.
        target.home_score = _NOISE
        target.away_score = _NOISE
        target.status = "Final"
        for player in mlb_players:
            session.add(
                MLBPlayerGameStat(
                    player_id=player.id,
                    game_id=target.id,
                    hits=_NOISE,
                    total_bases=_NOISE,
                    rbi=_NOISE,
                    runs=_NOISE,
                    strikeouts_pitcher=_NOISE,
                )
            )

        # (b) Foreign-sport (NBA) noise.
        # An NBA game pointing at the SAME MLB team rows, dated within the
        # lookback with extreme scores: only the sport==MLB scope (not a team-id
        # mismatch) can keep it out of the game-market sample.
        nba_same_rows = Game(
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            game_date=_TARGET_DATE - timedelta(days=1),
            status="Final",
            sport=Sport.NBA,
            nba_game_id="900001",
            home_score=_NOISE,
            away_score=_NOISE,
        )
        session.add(nba_same_rows)
        session.flush()

        # An MLB-shaped stat line attached to that NBA game for an MLB roster
        # player: only the sport==MLB join scope keeps it out of the prop sample.
        session.add(
            MLBPlayerGameStat(
                player_id=mlb_players[0].id,
                game_id=nba_same_rows.id,
                hits=_NOISE,
                total_bases=_NOISE,
                rbi=_NOISE,
                runs=_NOISE,
                strikeouts_pitcher=_NOISE,
            )
        )

        # A fully independent NBA slate (its own teams, players, game, stats).
        nba_home = Team(name="NBA Home", sport=Sport.NBA, nba_team_id=1610612737)
        nba_away = Team(name="NBA Away", sport=Sport.NBA, nba_team_id=1610612738)
        session.add_all([nba_home, nba_away])
        session.flush()
        nba_player = Player(
            full_name="NBA Star",
            team_id=nba_home.id,
            sport=Sport.NBA,
            nba_player_id=2544,
            primary_position="G",
        )
        session.add(nba_player)
        session.flush()
        nba_game = Game(
            home_team_id=nba_home.id,
            away_team_id=nba_away.id,
            game_date=_TARGET_DATE - timedelta(days=2),
            status="Final",
            sport=Sport.NBA,
            nba_game_id="900002",
            home_score=_NOISE,
            away_score=_NOISE,
        )
        session.add(nba_game)
        session.flush()
        session.add(
            PlayerGameStat(
                player_id=nba_player.id,
                game_id=nba_game.id,
                points=_NOISE,
                rebounds=_NOISE,
                assists=_NOISE,
                minutes=48.0,
            )
        )
        session.commit()

        # --- Re-price: results must be identical to the baseline ---
        after_markets = _market_fingerprint(build_mlb_game_markets(session, target))
        after_props = _props_fingerprint(build_mlb_game_prop_lines_bundle(session, target))

        assert after_markets == baseline_markets, (
            "MLB game markets changed after adding the target game's own results "
            "and foreign-sport noise; samples are not properly excluding them."
        )
        assert after_props == baseline_props, (
            "MLB prop lines changed after adding the target game's own results "
            "and foreign-sport noise; samples are not properly excluding them."
        )
    finally:
        gen.close()
