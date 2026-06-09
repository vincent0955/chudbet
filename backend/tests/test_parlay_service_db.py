"""DB-backed tests for parlay creation (player props + normal approximation)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.api.parlay_schemas import LegIn, ParlayCreate
from app.db.enums import LegDirection, ParlayMode, StatType
from app.db.models import Game, Player, PlayerGameStat, Team
from app.parlay.service import create_parlay, fetch_stat_series


def _seed_player_with_history(session: Session, points: list[int]) -> tuple[Player, list[Game]]:
    team = Team(name="Test Team", nba_team_id=10)
    session.add(team)
    session.flush()
    player = Player(full_name="Test Player", team_id=team.id, nba_player_id=100)
    session.add(player)
    session.flush()

    games: list[Game] = []
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
        games.append(game)
    session.flush()
    return player, games


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
        player, _ = _seed_player_with_history(session, [20, 22, 24, 26, 28])
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            legs=[
                LegIn(
                    player_id=player.id,
                    stat_type=StatType.PTS,
                    line=10.0,  # well below ~24 avg => high OVER probability
                    direction=LegDirection.OVER,
                )
            ],
        )
        parlay = create_parlay(session, body)
        assert parlay.id is not None
        assert parlay.total_legs == 1
        assert parlay.mode == ParlayMode.STANDARD
        assert parlay.wager_on_hit is True
        assert parlay.p_hit is not None and parlay.p_hit > 0.9
        assert parlay.fair_decimal_odds is not None and parlay.fair_decimal_odds > 1.0
        assert len(parlay.legs) == 1
        assert parlay.legs[0].leg_probability == pytest.approx(parlay.p_hit)

    def test_anti_parlay_inverts_probability(self, session: Session) -> None:
        player, _ = _seed_player_with_history(session, [20, 22, 24, 26, 28])
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            wager_on_hit=False,
            legs=[
                LegIn(player_id=player.id, stat_type=StatType.PTS, line=10.0, direction=LegDirection.OVER)
            ],
        )
        parlay = create_parlay(session, body)
        # p_hit stays the probability the parlay hits; fair odds price the anti side (1 - p_hit).
        assert parlay.p_hit > 0.9
        assert parlay.wager_on_hit is False
        assert parlay.fair_decimal_odds == pytest.approx(1.0 / (1.0 - parlay.p_hit))

    def test_requires_two_games_of_history(self, session: Session) -> None:
        player, _ = _seed_player_with_history(session, [25])
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            legs=[
                LegIn(player_id=player.id, stat_type=StatType.PTS, line=10.0, direction=LegDirection.OVER)
            ],
        )
        with pytest.raises(ValueError, match="at least 2 games"):
            create_parlay(session, body)

    def test_unknown_player_raises(self, session: Session) -> None:
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            legs=[LegIn(player_id=999, stat_type=StatType.PTS, line=10.0, direction=LegDirection.OVER)],
        )
        with pytest.raises(ValueError, match="not found"):
            create_parlay(session, body)


class TestCreateParlayXOfY:
    def test_x_of_y_is_deterministic_with_seed(self, session: Session) -> None:
        player, _ = _seed_player_with_history(session, [20, 22, 24, 26, 28])
        legs = [
            LegIn(player_id=player.id, stat_type=StatType.PTS, line=10.0, direction=LegDirection.OVER),
            LegIn(player_id=player.id, stat_type=StatType.REB, line=2.0, direction=LegDirection.OVER),
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
        player, _ = _seed_player_with_history(session, [20, 22, 24, 26, 28])
        body = ParlayCreate(
            mode=ParlayMode.X_OF_Y,
            k_required=2,
            simulation_iterations=2_000,
            rng_seed=1,
            legs=[
                LegIn(player_id=player.id, stat_type=StatType.PTS, line=10.0, direction=LegDirection.OVER),
                LegIn(player_id=player.id, stat_type=StatType.AST, line=1.0, direction=LegDirection.OVER),
            ],
        )
        parlay = create_parlay(session, body)
        assert parlay.k_required == 2
        assert parlay.total_legs == 2
