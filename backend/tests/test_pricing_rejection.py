"""Rejection and line-drift tests for the server-authoritative pricing engine.

Covers Requirements 3.2, 3.7, 4.3, 7.5, 7.6 and design Correctness Property 6
(a rejected ticket never persists Parlay/Wager rows).

These exercise the real engine via ``create_parlay`` against an in-memory SQLite
session (see tests/conftest.py), seeding only the rows each scenario needs.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.parlay_schemas import GameLegIn, LegIn, ParlayCreate
from app.db.enums import (
    GameMarketType,
    GameSelection,
    LegDirection,
    ParlayMode,
    StatType,
)
from app.db.models import Game, Parlay, Player, PlayerGameStat, Team, Wager
from app.parlay.pricing import LineDriftError, PricingValidationError
from app.parlay.service import create_parlay

# Target (pre-game) game date; all historical stat games are dated before this.
TARGET_DATE = date(2026, 2, 1)
PRE_GAME_STATUS = "7:30 pm ET"


def _seed_team(session: Session, name: str, nba_id: int) -> Team:
    team = Team(name=name, nba_team_id=nba_id)
    session.add(team)
    session.flush()
    return team


def _seed_target_game(session: Session) -> Game:
    """Seed a pre-game matchup between two fresh teams and return it."""
    home = _seed_team(session, "Home Town", 100)
    away = _seed_team(session, "Away City", 200)
    game = Game(
        home_team_id=home.id,
        away_team_id=away.id,
        game_date=TARGET_DATE,
        status=PRE_GAME_STATUS,
        nba_game_id="0022000999",
    )
    session.add(game)
    session.flush()
    return game


def _seed_player_with_history(
    session: Session,
    target_game: Game,
    *,
    points: list[int],
) -> Player:
    """Seed a player on the target game's home team plus one FINAL game per points value.

    Each historical game is dated strictly before the target game so the prop
    bundle's lookback (games before the target date) picks them up.
    """
    player = Player(
        full_name="Prop Player",
        team_id=target_game.home_team_id,
        nba_player_id=500,
    )
    session.add(player)
    session.flush()

    for i, pts in enumerate(points):
        hist = Game(
            home_team_id=target_game.home_team_id,
            away_team_id=target_game.away_team_id,
            game_date=date(2026, 1, i + 1),
            status="Final",
            nba_game_id=f"002200{i:04d}",
        )
        session.add(hist)
        session.flush()
        session.add(
            PlayerGameStat(
                player_id=player.id,
                game_id=hist.id,
                points=pts,
                rebounds=5,
                assists=3,
            )
        )
    session.flush()
    return player


def test_prop_line_not_offered_raises_validation_error(session: Session) -> None:
    """Fewer than the minimum samples => no line => PricingValidationError (Req 3.2)."""
    game = _seed_target_game(session)
    player = _seed_player_with_history(session, game, points=[20, 20])  # only 2 < 3 samples

    body = ParlayCreate(
        mode=ParlayMode.STANDARD,
        legs=[
            LegIn(
                player_id=player.id,
                game_id=game.id,
                stat_type=StatType.PTS,
                line=10.0,
                direction=LegDirection.OVER,
            )
        ],
    )
    with pytest.raises(PricingValidationError):
        create_parlay(session, body)


def test_prop_line_spoof_raises_line_drift_error(session: Session) -> None:
    """A client prop line that differs from the authoritative line => LineDriftError (Req 4.3)."""
    game = _seed_target_game(session)
    # >= 3 identical samples => a deterministic authoritative half-point line.
    player = _seed_player_with_history(session, game, points=[20, 20, 20, 20])

    body = ParlayCreate(
        mode=ParlayMode.STANDARD,
        legs=[
            LegIn(
                player_id=player.id,
                game_id=game.id,
                stat_type=StatType.PTS,
                line=5.0,  # in schema range but nowhere near the ~20.5 authoritative line
                direction=LegDirection.OVER,
            )
        ],
    )
    with pytest.raises(LineDriftError):
        create_parlay(session, body)


def test_prop_leg_missing_game_id_raises_validation_error(session: Session) -> None:
    """Player prop legs require a game_id; omitting it => PricingValidationError (Req 3.7)."""
    body = ParlayCreate(
        mode=ParlayMode.STANDARD,
        legs=[
            LegIn(
                player_id=1,
                game_id=None,
                stat_type=StatType.PTS,
                line=10.0,
                direction=LegDirection.OVER,
            )
        ],
    )
    with pytest.raises(PricingValidationError, match="game_id"):
        create_parlay(session, body)


def test_game_total_line_drift_raises_line_drift_error(session: Session) -> None:
    """A game TOTAL line far from the authoritative default (222.5) => LineDriftError (Req 4.3)."""
    game = _seed_target_game(session)

    body = ParlayCreate(
        mode=ParlayMode.STANDARD,
        game_legs=[
            GameLegIn(
                game_id=game.id,
                market_type=GameMarketType.TOTAL,
                selection=GameSelection.OVER,
                line=100.5,  # default total line is 222.5 => drift beyond 0.0 tolerance
                odds_american=-110,
            )
        ],
    )
    with pytest.raises(LineDriftError):
        create_parlay(session, body)


def test_rejected_ticket_persists_nothing(session: Session) -> None:
    """Property 6 / Req 7.5: a rejected create_parlay leaves zero Parlay and Wager rows."""
    game = _seed_target_game(session)

    body = ParlayCreate(
        mode=ParlayMode.STANDARD,
        game_legs=[
            GameLegIn(
                game_id=game.id,
                market_type=GameMarketType.TOTAL,
                selection=GameSelection.OVER,
                line=100.5,
                odds_american=-110,
            )
        ],
    )
    with pytest.raises(LineDriftError):
        create_parlay(session, body)

    parlay_count = session.scalar(select(func.count()).select_from(Parlay))
    wager_count = session.scalar(select(func.count()).select_from(Wager))
    assert parlay_count == 0
    assert wager_count == 0
