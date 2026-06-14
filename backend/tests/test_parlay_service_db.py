"""DB-backed tests for parlay creation (player props + normal approximation)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.api.parlay_schemas import LegIn, ParlayCreate
from app.db.enums import LegDirection, ParlayMode, StatType
from app.db.models import Game, Player, PlayerGameStat, Team
from app.parlay import pricing
from app.parlay.pricing import PricingValidationError
from app.parlay.service import create_parlay, fetch_stat_series


def _seed_player_with_history(session: Session, points: list[int]) -> tuple[Player, Game]:
    """Seed a player with prior FINAL games (for line history) plus a future
    PRE-GAME target game where the player's team plays an opponent.

    Player-prop legs are now server-authoritative: they require a ``game_id``
    pointing at a pre-game target, and a published line only exists when the
    player has at least ``GAME_PROP_MIN_SAMPLES`` (3) prior games. Returns the
    player and the target game whose id the leg must reference.
    """
    team = Team(name="Test Team", nba_team_id=10)
    opponent = Team(name="Opponent", nba_team_id=11)
    session.add_all([team, opponent])
    session.flush()
    player = Player(full_name="Test Player", team_id=team.id, nba_player_id=100)
    session.add(player)
    session.flush()

    for i, pts in enumerate(points):
        game = Game(
            home_team_id=team.id,
            away_team_id=team.id,
            game_date=date(2026, 1, i + 1),
            status="Final",
            nba_game_id=f"002200{i:04d}",
        )
        session.add(game)
        session.flush()
        session.add(
            PlayerGameStat(player_id=player.id, game_id=game.id, points=pts, rebounds=5, assists=3)
        )
    session.flush()

    # Future pre-game target: the player's team hosts an opponent. Its date is
    # after every history game so all prior games count toward the line.
    target = Game(
        home_team_id=team.id,
        away_team_id=opponent.id,
        game_date=date(2026, 2, 1),
        status="7:30 pm ET",
        nba_game_id="0022009999",
    )
    session.add(target)
    session.flush()
    return player, target


class TestFetchStatSeries:
    def test_returns_recent_values_first(self, session: Session) -> None:
        player, _ = _seed_player_with_history(session, [10, 20, 30])
        series = fetch_stat_series(session, player.id, StatType.PTS, lookback=10)
        assert series == [30.0, 20.0, 10.0]

    def test_respects_lookback_limit(self, session: Session) -> None:
        player, _ = _seed_player_with_history(session, [10, 20, 30, 40])
        series = fetch_stat_series(session, player.id, StatType.PTS, lookback=2)
        assert series == [40.0, 30.0]


class TestCreateParlayStandard:
    def test_persists_legs_and_probabilities(self, session: Session) -> None:
        player, target = _seed_player_with_history(session, [20, 22, 24, 26, 28])
        line = pricing.authoritative_prop_line(session, target, player.id, StatType.PTS)
        assert line is not None  # >= 3 prior games => a line exists
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            legs=[
                LegIn(
                    player_id=player.id,
                    game_id=target.id,
                    stat_type=StatType.PTS,
                    line=line,  # exactly the authoritative line (no drift)
                    direction=LegDirection.OVER,
                )
            ],
        )
        parlay = create_parlay(session, body)
        assert parlay.id is not None
        assert parlay.total_legs == 1
        assert parlay.mode == ParlayMode.STANDARD
        assert parlay.wager_on_hit is True
        # Probability is server-derived from history at the authoritative line.
        assert parlay.p_hit is not None and 0.0 < parlay.p_hit < 1.0
        assert parlay.fair_decimal_odds is not None and parlay.fair_decimal_odds > 1.0
        assert len(parlay.legs) == 1
        # The persisted line is the authoritative server line, not a client choice.
        assert parlay.legs[0].line == line
        assert parlay.legs[0].leg_probability == pytest.approx(parlay.p_hit)

    def test_anti_parlay_inverts_probability(self, session: Session) -> None:
        player, target = _seed_player_with_history(session, [20, 22, 24, 26, 28])
        line = pricing.authoritative_prop_line(session, target, player.id, StatType.PTS)
        assert line is not None
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            wager_on_hit=False,
            legs=[
                LegIn(
                    player_id=player.id,
                    game_id=target.id,
                    stat_type=StatType.PTS,
                    line=line,
                    direction=LegDirection.OVER,
                )
            ],
        )
        parlay = create_parlay(session, body)
        # p_hit stays the probability the parlay hits; fair odds price the anti side (1 - p_hit).
        assert 0.0 < parlay.p_hit < 1.0
        assert parlay.wager_on_hit is False
        assert parlay.fair_decimal_odds == pytest.approx(1.0 / (1.0 - parlay.p_hit))

    def test_requires_two_games_of_history(self, session: Session) -> None:
        # A single prior game is below the min-samples threshold, so no
        # authoritative line is published and the leg is rejected.
        player, target = _seed_player_with_history(session, [25])
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            legs=[
                LegIn(
                    player_id=player.id,
                    game_id=target.id,
                    stat_type=StatType.PTS,
                    line=10.0,
                    direction=LegDirection.OVER,
                )
            ],
        )
        with pytest.raises(PricingValidationError):
            create_parlay(session, body)

    def test_unknown_player_raises(self, session: Session) -> None:
        # The player is not on the target game's roster, so no line is offered.
        _, target = _seed_player_with_history(session, [20, 22, 24, 26, 28])
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            legs=[
                LegIn(
                    player_id=999,
                    game_id=target.id,
                    stat_type=StatType.PTS,
                    line=10.0,
                    direction=LegDirection.OVER,
                )
            ],
        )
        with pytest.raises(PricingValidationError):
            create_parlay(session, body)


class TestCreateParlayXOfY:
    def test_x_of_y_is_deterministic_with_seed(self, session: Session) -> None:
        player, target = _seed_player_with_history(session, [20, 22, 24, 26, 28])
        pts_line = pricing.authoritative_prop_line(session, target, player.id, StatType.PTS)
        reb_line = pricing.authoritative_prop_line(session, target, player.id, StatType.REB)
        assert pts_line is not None and reb_line is not None
        legs = [
            LegIn(
                player_id=player.id,
                game_id=target.id,
                stat_type=StatType.PTS,
                line=pts_line,
                direction=LegDirection.OVER,
            ),
            LegIn(
                player_id=player.id,
                game_id=target.id,
                stat_type=StatType.REB,
                line=reb_line,
                direction=LegDirection.OVER,
            ),
        ]

        def _build() -> float:
            body = ParlayCreate(
                mode=ParlayMode.X_OF_Y,
                k_required=1,
                simulation_iterations=5_000,
                rng_seed=123,
                legs=legs,
            )
            return create_parlay(session, body).p_hit

        assert _build() == _build()

    def test_x_of_y_records_k_required(self, session: Session) -> None:
        player, target = _seed_player_with_history(session, [20, 22, 24, 26, 28])
        pts_line = pricing.authoritative_prop_line(session, target, player.id, StatType.PTS)
        ast_line = pricing.authoritative_prop_line(session, target, player.id, StatType.AST)
        assert pts_line is not None and ast_line is not None
        body = ParlayCreate(
            mode=ParlayMode.X_OF_Y,
            k_required=2,
            simulation_iterations=2_000,
            rng_seed=1,
            legs=[
                LegIn(
                    player_id=player.id,
                    game_id=target.id,
                    stat_type=StatType.PTS,
                    line=pts_line,
                    direction=LegDirection.OVER,
                ),
                LegIn(
                    player_id=player.id,
                    game_id=target.id,
                    stat_type=StatType.AST,
                    line=ast_line,
                    direction=LegDirection.OVER,
                ),
            ],
        )
        parlay = create_parlay(session, body)
        assert parlay.k_required == 2
        assert parlay.total_legs == 2
