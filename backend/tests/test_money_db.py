"""DB-backed tests for the ledger / wager money service (in-memory SQLite)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.parlay_schemas import GameLegIn, ParlayCreate
from app.db.enums import (
    GameMarketType,
    GameSelection,
    LedgerEntryType,
    ParlayMode,
    WagerStatus,
)
from app.db.models import Game, LedgerEntry, Team, Wager
from app.services import money
from app.services.money import InsufficientBalanceError


def _seed_game(session: Session, *, nba_game_id: str = "0022000001", status: str = "7:30 pm ET") -> Game:
    home = Team(name="Home Town", nba_team_id=int(nba_game_id[-3:]) + 100)
    away = Team(name="Away City", nba_team_id=int(nba_game_id[-3:]) + 200)
    session.add_all([home, away])
    session.flush()
    game = Game(
        home_team_id=home.id,
        away_team_id=away.id,
        game_date=date(2026, 1, 15),
        status=status,
        nba_game_id=nba_game_id,
    )
    session.add(game)
    session.flush()
    return game


def _moneyline_body(game_id: int) -> ParlayCreate:
    return ParlayCreate(
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


class TestCreateAccount:
    def test_starts_with_zero_balance(self, session: Session) -> None:
        account = money.create_account(session)
        assert account.id is not None
        assert account.balance_cents == 0


class TestDeposit:
    def test_credits_balance_and_writes_ledger(self, session: Session) -> None:
        account = money.create_account(session)
        updated, entry, duplicated = money.deposit(session, account.id, amount_cents=5000)
        assert duplicated is False
        assert updated.balance_cents == 5000
        assert entry.entry_type == LedgerEntryType.DEPOSIT
        assert entry.amount_cents == 5000
        assert entry.balance_after_cents == 5000

    def test_multiple_deposits_accumulate(self, session: Session) -> None:
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=1000)
        updated, _, _ = money.deposit(session, account.id, amount_cents=2500)
        assert updated.balance_cents == 3500

    def test_non_positive_amount_raises(self, session: Session) -> None:
        account = money.create_account(session)
        with pytest.raises(ValueError):
            money.deposit(session, account.id, amount_cents=0)
        with pytest.raises(ValueError):
            money.deposit(session, account.id, amount_cents=-100)

    def test_missing_account_raises(self, session: Session) -> None:
        with pytest.raises(ValueError, match="not found"):
            money.deposit(session, 999, amount_cents=100)

    def test_idempotency_key_is_not_double_counted(self, session: Session) -> None:
        account = money.create_account(session)
        _, first, dup1 = money.deposit(session, account.id, amount_cents=4200, idempotency_key="abc")
        updated, second, dup2 = money.deposit(session, account.id, amount_cents=4200, idempotency_key="abc")
        assert dup1 is False
        assert dup2 is True
        assert first.id == second.id
        assert updated.balance_cents == 4200

    def test_idempotency_key_owned_by_other_account_raises(self, session: Session) -> None:
        a = money.create_account(session)
        b = money.create_account(session)
        money.deposit(session, a.id, amount_cents=100, idempotency_key="shared")
        with pytest.raises(ValueError, match="another account"):
            money.deposit(session, b.id, amount_cents=100, idempotency_key="shared")


class TestPlaceWager:
    def test_debits_stake_and_records_wager(self, session: Session) -> None:
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=10_000)
        game = _seed_game(session)
        wager, updated, dup = money.place_wager(
            session,
            account.id,
            stake_cents=2_000,
            offered_decimal_odds=None,
            parlay_body=_moneyline_body(game.id),
        )
        assert dup is False
        assert wager.status == WagerStatus.OPEN
        assert wager.stake_cents == 2_000
        assert updated.balance_cents == 8_000
        assert wager.potential_return_cents == round(2_000 * wager.offered_decimal_odds)

    def test_uses_offered_odds_when_provided(self, session: Session) -> None:
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=10_000)
        game = _seed_game(session)
        wager, _, _ = money.place_wager(
            session,
            account.id,
            stake_cents=1_000,
            offered_decimal_odds=3.0,
            parlay_body=_moneyline_body(game.id),
        )
        assert wager.offered_decimal_odds == 3.0
        assert wager.potential_return_cents == 3_000

    def test_insufficient_balance_raises(self, session: Session) -> None:
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=500)
        game = _seed_game(session)
        with pytest.raises(InsufficientBalanceError):
            money.place_wager(
                session,
                account.id,
                stake_cents=1_000,
                offered_decimal_odds=2.0,
                parlay_body=_moneyline_body(game.id),
            )

    def test_non_positive_stake_raises(self, session: Session) -> None:
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=10_000)
        game = _seed_game(session)
        with pytest.raises(ValueError):
            money.place_wager(
                session,
                account.id,
                stake_cents=0,
                offered_decimal_odds=2.0,
                parlay_body=_moneyline_body(game.id),
            )

    def test_stake_above_maximum_raises(self, session: Session) -> None:
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=money.MAX_STAKE_CENTS + 1_000)
        game = _seed_game(session)
        with pytest.raises(ValueError, match="maximum"):
            money.place_wager(
                session,
                account.id,
                stake_cents=money.MAX_STAKE_CENTS + 1,
                offered_decimal_odds=2.0,
                parlay_body=_moneyline_body(game.id),
            )

    def test_idempotent_wager_not_placed_twice(self, session: Session) -> None:
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=10_000)
        game = _seed_game(session)
        first, _, dup1 = money.place_wager(
            session,
            account.id,
            stake_cents=1_000,
            offered_decimal_odds=2.0,
            parlay_body=_moneyline_body(game.id),
            idempotency_key="bet-1",
        )
        second, account_after, dup2 = money.place_wager(
            session,
            account.id,
            stake_cents=1_000,
            offered_decimal_odds=2.0,
            parlay_body=_moneyline_body(game.id),
            idempotency_key="bet-1",
        )
        assert dup1 is False
        assert dup2 is True
        assert first.id == second.id
        # Only one stake debited.
        assert account_after.balance_cents == 9_000

    def test_wager_on_live_game_is_rejected(self, session: Session) -> None:
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=10_000)
        game = _seed_game(session, status="Q3 4:21")
        with pytest.raises(ValueError):
            money.place_wager(
                session,
                account.id,
                stake_cents=1_000,
                offered_decimal_odds=2.0,
                parlay_body=_moneyline_body(game.id),
            )


def _open_wager(session: Session, *, stake: int = 1_000, odds: float = 2.0) -> Wager:
    account = money.create_account(session)
    money.deposit(session, account.id, amount_cents=10_000)
    game = _seed_game(session)
    wager, _, _ = money.place_wager(
        session,
        account.id,
        stake_cents=stake,
        offered_decimal_odds=odds,
        parlay_body=_moneyline_body(game.id),
    )
    return wager


class TestSettleWager:
    def test_win_credits_full_return(self, session: Session) -> None:
        wager = _open_wager(session, stake=1_000, odds=2.0)
        money.settle_wager_win(session, wager)
        assert wager.status == WagerStatus.WON
        account = session.get(money.Account, wager.account_id)
        # 10_000 - 1_000 stake + 2_000 payout
        assert account.balance_cents == 11_000
        payout = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.reference_id == wager.id,
                LedgerEntry.entry_type == LedgerEntryType.WAGER_PAYOUT,
            )
        )
        assert payout is not None
        assert payout.amount_cents == 2_000

    def test_loss_keeps_balance_and_writes_no_credit(self, session: Session) -> None:
        wager = _open_wager(session, stake=1_000, odds=2.0)
        money.settle_wager_loss(session, wager)
        assert wager.status == WagerStatus.LOST
        account = session.get(money.Account, wager.account_id)
        assert account.balance_cents == 9_000

    def test_void_refunds_stake(self, session: Session) -> None:
        wager = _open_wager(session, stake=1_000, odds=2.0)
        money.settle_wager_void(session, wager)
        assert wager.status == WagerStatus.VOID
        account = session.get(money.Account, wager.account_id)
        assert account.balance_cents == 10_000
        refund = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.reference_id == wager.id,
                LedgerEntry.entry_type == LedgerEntryType.WAGER_VOID,
            )
        )
        assert refund is not None
        assert refund.amount_cents == 1_000

    def test_cannot_settle_already_settled_wager(self, session: Session) -> None:
        wager = _open_wager(session)
        money.settle_wager_win(session, wager)
        with pytest.raises(ValueError, match="not open"):
            money.settle_wager_win(session, wager)
        with pytest.raises(ValueError, match="not open"):
            money.settle_wager_loss(session, wager)
        with pytest.raises(ValueError, match="not open"):
            money.settle_wager_void(session, wager)

    def test_ledger_balance_after_matches_account(self, session: Session) -> None:
        wager = _open_wager(session, stake=2_500, odds=2.0)
        money.settle_wager_win(session, wager)
        account = session.get(money.Account, wager.account_id)
        latest = session.scalar(
            select(LedgerEntry)
            .where(LedgerEntry.account_id == account.id)
            .order_by(LedgerEntry.id.desc())
            .limit(1)
        )
        assert latest is not None
        assert latest.balance_after_cents == account.balance_cents
        # Ledger entries should net to the running balance.
        total = session.scalar(
            select(func.sum(LedgerEntry.amount_cents)).where(LedgerEntry.account_id == account.id)
        )
        assert total == account.balance_cents
