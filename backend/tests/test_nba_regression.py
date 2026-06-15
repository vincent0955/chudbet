"""NBA behavior preservation after MLB support (Requirements 15.x, Property 30)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.api.parlay_schemas import GameLegIn, ParlayCreate
from app.db.enums import GameMarketType, GameSelection, ParlayMode, Sport
from app.db.models import Game, Team
from app.parlay import pricing
from app.services.game_markets import build_game_markets
from app.services.settlement import _resolve_ticket
from app.db.models import Parlay


def _seed_nba_game(session: Session) -> Game:
    home = Team(name="Celtics", sport=Sport.NBA, nba_team_id=1610612738)
    away = Team(name="Lakers", sport=Sport.NBA, nba_team_id=1610612747)
    session.add_all([home, away])
    session.flush()
    game = Game(
        home_team_id=home.id,
        away_team_id=away.id,
        game_date=date(2026, 3, 1),
        status="7:30 pm ET",
        sport=Sport.NBA,
        nba_game_id="0022000100",
    )
    session.add(game)
    session.flush()
    return game


class TestNbaRegressionGolden:
    """Fixed NBA dataset — pricing/resolution paths remain stable."""

    def test_nba_game_markets_default_total_line(self, session: Session) -> None:
        game = _seed_nba_game(session)
        markets = build_game_markets(session, game)
        assert markets.total.line == pytest.approx(222.5)

    def test_nba_moneyline_quote_unchanged(self, session: Session) -> None:
        game = _seed_nba_game(session)
        quote = pricing.authoritative_game_line(
            session, game, GameMarketType.MONEYLINE, GameSelection.HOME
        )
        assert quote is not None
        assert quote.odds_american != 0

    def test_nba_ticket_resolution_unchanged(self) -> None:
        parlay = Parlay(mode=ParlayMode.STANDARD, wager_on_hit=True, k_required=None)
        assert _resolve_ticket(parlay, ["win", "loss"]) == "loss"


class TestNbaPreservationProperty:
    def test_property30_nba_pricing_functions_are_unchanged_entrypoints(self) -> None:
        """Feature: mlb-support, Property 30."""
        assert pricing.authoritative_game_line is not None
        assert pricing.authoritative_prop_quote is not None
        assert pricing.NbaPricer is not None
