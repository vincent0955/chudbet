"""Backward-compatibility, settlement, and safeguard tests for server-authoritative pricing.

Covers Requirements 8.1, 8.3, 8.5, 8.6, 9.1, 9.2, 10.1-10.6 and design Property 8
(payout consistency at settlement). Uses the in-memory ``session`` fixture and
local seed helpers; a moneyline ticket prices with no score history.
"""

from __future__ import annotations

import math
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.parlay_schemas import GameLegIn, ParlayCreate
from app.db.enums import (
    GameMarketType,
    GameSelection,
    LedgerEntryType,
    ParlayMode,
    WagerStatus,
)
from app.db.models import Account, Game, LedgerEntry, Team, Wager
from app.services import money
from app.services.money import InsufficientBalanceError
from app.services.settlement import settle_open_wagers


def _seed_game(session: Session, *, nba_game_id: str = "0022000001", status: str = "7:30 pm ET") -> Game:
    suffix = int(nba_game_id[-3:])
    home = Team(name=f"Home {suffix}", nba_team_id=suffix + 100)
    away = Team(name=f"Away {suffix}", nba_team_id=suffix + 200)
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


def _funded_account(session: Session, *, balance: int = 10_000) -> Account:
    account = money.create_account(session)
    money.deposit(session, account.id, amount_cents=balance)
    return account


class TestBackwardCompatibility:
    def test_omitting_offered_odds_succeeds_with_server_payout(self, session: Session) -> None:
        """Req 9.1, 9.2: a request without ``offered_decimal_odds`` is priced server-side."""
        account = _funded_account(session)
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
        # Server payout odds are valid and strictly profitable on a win.
        assert wager.offered_decimal_odds > 1.0
        assert wager.potential_return_cents == math.floor(2_000 * wager.offered_decimal_odds)
        assert updated.balance_cents == 10_000 - 2_000


class TestSettlementConsistency:
    def test_win_pays_stored_potential_return(self, session: Session) -> None:
        """Req 8.3 / Property 8: a won wager pays exactly the stored potential return."""
        account = _funded_account(session)
        game = _seed_game(session)
        wager, _, _ = money.place_wager(
            session,
            account.id,
            stake_cents=1_000,
            offered_decimal_odds=None,
            parlay_body=_moneyline_body(game.id),
        )
        stored_return = wager.potential_return_cents

        # Home team wins; game is final.
        game.home_score = 120
        game.away_score = 100
        game.status = "Final"
        session.flush()

        counts = settle_open_wagers(session)
        assert counts["won"] == 1
        session.refresh(wager)
        assert wager.status == WagerStatus.WON

        account_after = session.get(Account, wager.account_id)
        # Credited exactly the stored potential return (stake was already debited).
        assert account_after.balance_cents == 10_000 - 1_000 + stored_return
        payout = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.reference_id == wager.id,
                LedgerEntry.entry_type == LedgerEntryType.WAGER_PAYOUT,
            )
        )
        assert payout is not None
        assert payout.amount_cents == stored_return

    def test_void_refunds_stake_zero_winnings(self, session: Session) -> None:
        """Req 8.5, 8.6 / Property 8: a void refunds the stake and pays no winnings."""
        account = _funded_account(session)
        game = _seed_game(session)
        wager, _, _ = money.place_wager(
            session,
            account.id,
            stake_cents=1_000,
            offered_decimal_odds=None,
            parlay_body=_moneyline_body(game.id),
        )

        # A tie on a moneyline leg is graded as void by settlement.
        game.home_score = 100
        game.away_score = 100
        game.status = "Final"
        session.flush()

        counts = settle_open_wagers(session)
        assert counts["void"] == 1
        session.refresh(wager)
        assert wager.status == WagerStatus.VOID

        account_after = session.get(Account, wager.account_id)
        # Stake refunded exactly; no net winnings.
        assert account_after.balance_cents == 10_000
        refund = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.reference_id == wager.id,
                LedgerEntry.entry_type == LedgerEntryType.WAGER_VOID,
            )
        )
        assert refund is not None
        assert refund.amount_cents == 1_000
        # No payout (winnings) entry was written.
        payout = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.reference_id == wager.id,
                LedgerEntry.entry_type == LedgerEntryType.WAGER_PAYOUT,
            )
        )
        assert payout is None

    def test_settle_wager_void_pays_zero_winnings_directly(self, session: Session) -> None:
        """Req 8.5/8.6 unit-level: ``settle_wager_void`` refunds stake and zero winnings."""
        account = _funded_account(session)
        game = _seed_game(session)
        wager, _, _ = money.place_wager(
            session,
            account.id,
            stake_cents=1_500,
            offered_decimal_odds=None,
            parlay_body=_moneyline_body(game.id),
        )
        money.settle_wager_void(session, wager)
        assert wager.status == WagerStatus.VOID
        account_after = session.get(Account, wager.account_id)
        assert account_after.balance_cents == 10_000  # stake fully refunded
        payout = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.reference_id == wager.id,
                LedgerEntry.entry_type == LedgerEntryType.WAGER_PAYOUT,
            )
        )
        assert payout is None


class TestSafeguardsPreserved:
    def test_started_game_is_rejected(self, session: Session) -> None:
        """Req 10.1: a started/finished game cannot be wagered on."""
        account = _funded_account(session)
        game = _seed_game(session, status="Q3 4:21")
        with pytest.raises(ValueError):
            money.place_wager(
                session,
                account.id,
                stake_cents=1_000,
                offered_decimal_odds=None,
                parlay_body=_moneyline_body(game.id),
            )

    def test_stake_above_maximum_is_rejected(self, session: Session) -> None:
        """Req 10.2: stake above the server maximum is rejected."""
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=money.MAX_STAKE_CENTS + 10_000)
        game = _seed_game(session)
        with pytest.raises(ValueError, match="maximum"):
            money.place_wager(
                session,
                account.id,
                stake_cents=money.MAX_STAKE_CENTS + 1,
                offered_decimal_odds=None,
                parlay_body=_moneyline_body(game.id),
            )

    def test_insufficient_balance_is_rejected(self, session: Session) -> None:
        """Req 10.4: a stake above the available balance is rejected."""
        account = _funded_account(session, balance=500)
        game = _seed_game(session)
        with pytest.raises(InsufficientBalanceError):
            money.place_wager(
                session,
                account.id,
                stake_cents=1_000,
                offered_decimal_odds=None,
                parlay_body=_moneyline_body(game.id),
            )

    def test_idempotent_replay_returns_same_wager_and_debits_once(self, session: Session) -> None:
        """Req 10.5: replaying an idempotency key returns the original wager, debiting once."""
        account = _funded_account(session)
        game = _seed_game(session)
        first, _, dup1 = money.place_wager(
            session,
            account.id,
            stake_cents=1_000,
            offered_decimal_odds=None,
            parlay_body=_moneyline_body(game.id),
            idempotency_key="replay-1",
        )
        second, account_after, dup2 = money.place_wager(
            session,
            account.id,
            stake_cents=1_000,
            offered_decimal_odds=None,
            parlay_body=_moneyline_body(game.id),
            idempotency_key="replay-1",
        )
        assert dup1 is False
        assert dup2 is True
        assert first.id == second.id
        # Only one stake debit occurred.
        assert account_after.balance_cents == 9_000
        stakes = session.scalars(
            select(Wager).where(Wager.account_id == account.id)
        ).all()
        assert len(stakes) == 1
