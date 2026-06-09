"""End-to-end settlement against a real (SQLite) DB for game-leg wagers."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.api.parlay_schemas import GameLegIn, ParlayCreate
from app.db.enums import GameMarketType, GameSelection, ParlayMode, WagerStatus
from app.db.models import Account, Game, Team, Wager
from app.services import money
from app.services.settlement import settle_open_wagers


def _seed_game(session: Session, *, status: str = "7:30 pm ET") -> Game:
    home = Team(name="Home Town", nba_team_id=1)
    away = Team(name="Away City", nba_team_id=2)
    session.add_all([home, away])
    session.flush()
    game = Game(
        home_team_id=home.id,
        away_team_id=away.id,
        game_date=date(2026, 1, 15),
        status=status,
        nba_game_id="0022000099",
    )
    session.add(game)
    session.flush()
    return game


def _place_home_moneyline(session: Session, game_id: int, *, stake: int = 1_000, odds: float = 2.0) -> Wager:
    account = money.create_account(session)
    money.deposit(session, account.id, amount_cents=10_000)
    body = ParlayCreate(
        mode=ParlayMode.STANDARD,
        legs=[],
        game_legs=[
            GameLegIn(
                game_id=game_id,
                market_type=GameMarketType.MONEYLINE,
                selection=GameSelection.HOME,
                odds_american=-110,
            )
        ],
    )
    wager, _, _ = money.place_wager(
        session,
        account.id,
        stake_cents=stake,
        offered_decimal_odds=odds,
        parlay_body=body,
    )
    return wager


class TestSettleOpenWagers:
    def test_pending_while_game_not_final(self, session: Session) -> None:
        game = _seed_game(session)
        _place_home_moneyline(session, game.id)
        counts = settle_open_wagers(session)
        assert counts["open_seen"] == 1
        assert counts["pending"] == 1

    def test_home_win_settles_as_won_and_pays_out(self, session: Session) -> None:
        game = _seed_game(session)
        wager = _place_home_moneyline(session, game.id, stake=1_000, odds=2.0)
        game.home_score = 110
        game.away_score = 100
        game.status = "Final"
        session.flush()

        counts = settle_open_wagers(session)
        assert counts["won"] == 1
        session.refresh(wager)
        assert wager.status == WagerStatus.WON
        account = session.get(Account, wager.account_id)
        assert account.balance_cents == 11_000  # 10_000 - 1_000 + 2_000

    def test_home_loss_settles_as_lost(self, session: Session) -> None:
        game = _seed_game(session)
        wager = _place_home_moneyline(session, game.id, stake=1_000, odds=2.0)
        game.home_score = 95
        game.away_score = 100
        game.status = "Final"
        session.flush()

        counts = settle_open_wagers(session)
        assert counts["lost"] == 1
        session.refresh(wager)
        assert wager.status == WagerStatus.LOST
        account = session.get(Account, wager.account_id)
        assert account.balance_cents == 9_000

    def test_tie_moneyline_voids_and_refunds(self, session: Session) -> None:
        game = _seed_game(session)
        wager = _place_home_moneyline(session, game.id, stake=1_000, odds=2.0)
        game.home_score = 100
        game.away_score = 100
        game.status = "Final"
        session.flush()

        counts = settle_open_wagers(session)
        assert counts["void"] == 1
        session.refresh(wager)
        assert wager.status == WagerStatus.VOID
        account = session.get(Account, wager.account_id)
        assert account.balance_cents == 10_000

    def test_settled_wager_is_not_reprocessed(self, session: Session) -> None:
        game = _seed_game(session)
        _place_home_moneyline(session, game.id)
        game.home_score = 110
        game.away_score = 100
        game.status = "Final"
        session.flush()

        settle_open_wagers(session)
        second = settle_open_wagers(session)
        assert second["open_seen"] == 0
