"""Property-based test for MLB prop applicability by roster position.

Feature: mlb-support, Property 17
Validates: Requirements 9.1

Property 17 -- *Prop applicability follows roster position.* For an arbitrary
MLB game whose two rosters carry a mix of pitchers and non-pitchers, and with
enough prior history that every applicable stat clears the minimum-sample gate,
the prop bundle produced by
``app.mlb.prop_lines.build_mlb_game_prop_lines_bundle`` must offer each player
exactly the stat types that match their position:

- a **pitcher** (``primary_position`` ``P`` / ``SP`` / ``RP`` / ``LHP`` /
  ``RHP`` or a position naming "pitcher") is offered **only**
  ``STRIKEOUTS_PITCHER``, and
- a **non-pitcher** is offered **only** the four batter stats ``HITS`` /
  ``TOTAL_BASES`` / ``RBI`` / ``RUNS``.

The two families never overlap: a pitcher is never offered a batter stat and a
batter is never offered the pitcher stat.
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
from app.mlb.enums import MLBStatType
from app.mlb.prop_lines import build_mlb_game_prop_lines_bundle

# Target game date; all generated prior games sit strictly before it and within
# the prop lookback window (30 days) so they count as samples.
_TARGET_DATE = date(2024, 7, 20)

# Enough prior games that every player clears the default minimum sample size
# (5), so applicability -- not the sample gate -- decides what is offered.
_PRIOR_GAMES = 6

# Independent (test-side) definition of the position vocabularies, so the test
# does not borrow the implementation's classifier. Pitchers are offered only the
# strikeout stat; everyone else is offered the four batter stats.
_PITCHER_POSITIONS = ("P", "SP", "RP", "LHP", "RHP", "Pitcher")
_BATTER_POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "OF", "IF")

_EXPECTED_PITCHER_STATS = frozenset({MLBStatType.STRIKEOUTS_PITCHER.value})
_EXPECTED_BATTER_STATS = frozenset(
    {
        MLBStatType.HITS.value,
        MLBStatType.TOTAL_BASES.value,
        MLBStatType.RBI.value,
        MLBStatType.RUNS.value,
    }
)


# A single roster slot: a category ("pitcher" / "batter") paired with a position
# string drawn from the matching vocabulary. Carrying the category alongside the
# position lets the test assert the expected offering without re-deriving it.
def _slot(category: str, positions: tuple[str, ...]) -> st.SearchStrategy[dict]:
    return st.fixed_dictionaries(
        {"category": st.just(category), "position": st.sampled_from(positions)}
    )


_roster_slot = st.one_of(
    _slot("pitcher", _PITCHER_POSITIONS),
    _slot("batter", _BATTER_POSITIONS),
)

# A world: a non-empty roster for the home team and one for the away team, each a
# mix of pitchers and batters.
_world = st.fixed_dictionaries(
    {
        "home_roster": st.lists(_roster_slot, min_size=1, max_size=5),
        "away_roster": st.lists(_roster_slot, min_size=1, max_size=5),
    }
)


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


@settings(deadline=None, max_examples=120)
@given(world=_world)
def test_property17_prop_applicability_follows_roster_position(world: dict) -> None:
    """**Validates: Requirements 9.1**

    Feature: mlb-support, Property 17

    Build an arbitrary MLB game whose rosters mix pitchers and non-pitchers,
    give every player enough history to clear the sample gate, price the props,
    and assert each player is offered exactly the stat types for their position.
    """
    home_roster: list[dict] = world["home_roster"]
    away_roster: list[dict] = world["away_roster"]

    gen = _fresh_session()
    session = next(gen)
    try:
        home_team = Team(name="Home Nine", sport=Sport.MLB, mlb_team_id=147, abbreviation="HOM")
        away_team = Team(name="Away Nine", sport=Sport.MLB, mlb_team_id=111, abbreviation="AWY")
        session.add_all([home_team, away_team])
        session.flush()

        # Build rosters; remember each player's expected stat set by category.
        expected_by_player: dict[int, frozenset[str]] = {}
        players: list[Player] = []
        next_native = 1000
        for team, roster in ((home_team, home_roster), (away_team, away_roster)):
            for slot in roster:
                player = Player(
                    full_name=f"Player {next_native}",
                    team_id=team.id,
                    sport=Sport.MLB,
                    mlb_player_id=next_native,
                    primary_position=slot["position"],
                )
                players.append(player)
                next_native += 1
        session.add_all(players)
        session.flush()

        for player, slot in zip(
            players, [*home_roster, *away_roster], strict=True
        ):
            expected_by_player[player.id] = (
                _EXPECTED_PITCHER_STATS
                if slot["category"] == "pitcher"
                else _EXPECTED_BATTER_STATS
            )

        # Prior MLB games (within the lookback) so every player has >= min
        # samples and applicability, not the sample gate, governs the offering.
        prior_games: list[Game] = []
        next_game_native = 700000
        for i in range(_PRIOR_GAMES):
            prior_games.append(
                Game(
                    home_team_id=home_team.id,
                    away_team_id=away_team.id,
                    game_date=_TARGET_DATE - timedelta(days=i + 1),
                    status="Final",
                    sport=Sport.MLB,
                    mlb_game_id=str(next_game_native),
                    home_score=4,
                    away_score=3,
                )
            )
            next_game_native += 1
        session.add_all(prior_games)
        session.flush()

        # A non-negative box-score line for every player in every prior game.
        stat_rows: list[MLBPlayerGameStat] = []
        for g in prior_games:
            for player in players:
                stat_rows.append(
                    MLBPlayerGameStat(
                        player_id=player.id,
                        game_id=g.id,
                        hits=1,
                        total_bases=2,
                        rbi=1,
                        runs=1,
                        strikeouts_pitcher=3,
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

        # Every rostered player appears in the bundle.
        assert {pl.id for pl in bundle.players} == set(expected_by_player)

        for player_lines in bundle.players:
            offered = {sl.stat_type for sl in player_lines.stat_lines}
            expected = expected_by_player[player_lines.id]
            assert offered == set(expected), (
                f"player {player_lines.id} (position {player_lines.primary_position!r}) "
                f"offered {sorted(offered)}, expected {sorted(expected)}"
            )
    finally:
        gen.close()
