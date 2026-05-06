"""Ledger-backed balances and wager placement."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.parlay_schemas import ParlayCreate
from app.db.enums import LedgerEntryType, WagerStatus
from app.db.models import Account, LedgerEntry, Wager
from app.parlay.service import create_parlay

MAX_STAKE_CENTS = 500_000_00


class InsufficientBalanceError(Exception):
    """Raised when available balance is below the requested stake."""


def create_account(session: Session) -> Account:
    row = Account()
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def deposit(
    session: Session,
    account_id: int,
    *,
    amount_cents: int,
    idempotency_key: str | None = None,
    memo: str | None = None,
) -> tuple[Account, LedgerEntry, bool]:
    """
    Credit an account.

    Returns (account, ledger_entry, duplicated).

    Raises ValueError if the account is missing or idempotency key belongs to another account.
    """
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    if idempotency_key:
        existing = session.scalar(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key),
        )
        if existing is not None:
            if existing.account_id != account_id:
                raise ValueError("idempotency_key already belongs to another account")
            account = session.get(Account, account_id)
            if account is None:
                raise ValueError(f"account {account_id} not found")
            return account, existing, True

    stmt = select(Account).where(Account.id == account_id).with_for_update()
    account = session.scalar(stmt)
    if account is None:
        raise ValueError(f"account {account_id} not found")

    new_balance = account.balance_cents + amount_cents
    account.balance_cents = new_balance
    entry = LedgerEntry(
        account_id=account.id,
        entry_type=LedgerEntryType.DEPOSIT,
        amount_cents=amount_cents,
        balance_after_cents=new_balance,
        reference_type=None,
        reference_id=None,
        idempotency_key=idempotency_key,
        memo=memo,
    )
    session.add(entry)
    session.flush()
    session.refresh(account)
    session.refresh(entry)
    return account, entry, False


def place_wager(
    session: Session,
    account_id: int,
    *,
    stake_cents: int,
    offered_decimal_odds: float | None,
    parlay_body: ParlayCreate,
    idempotency_key: str | None = None,
    memo: str | None = None,
) -> tuple[Wager, Account, bool]:
    """
    Persist a parlay snapshot, debit stake into a wager, append ledger stake line.

    Returns (wager, account, duplicated).
    """
    if idempotency_key:
        existing = session.scalar(
            select(Wager).where(Wager.idempotency_key == idempotency_key),
        )
        if existing is not None:
            if existing.account_id != account_id:
                raise ValueError("idempotency_key already belongs to another account")
            stmt = select(Account).where(Account.id == account_id)
            account = session.scalar(stmt)
            if account is None:
                raise ValueError(f"account {account_id} not found")
            return existing, account, True

    if stake_cents <= 0:
        raise ValueError("stake_cents must be positive")
    if stake_cents > MAX_STAKE_CENTS:
        raise ValueError("stake_cents exceeds server maximum")

    stmt = select(Account).where(Account.id == account_id).with_for_update()
    account = session.scalar(stmt)
    if account is None:
        raise ValueError(f"account {account_id} not found")
    if account.balance_cents < stake_cents:
        raise InsufficientBalanceError

    parlay = create_parlay(session, parlay_body)
    odds = offered_decimal_odds if offered_decimal_odds is not None else parlay.fair_decimal_odds
    if odds is None or odds <= 1:
        raise ValueError("invalid_decimal_odds")

    potential_return = int(round(float(stake_cents) * float(odds)))
    new_balance = account.balance_cents - stake_cents
    account.balance_cents = new_balance

    wager = Wager(
        account_id=account.id,
        parlay_id=parlay.id,
        stake_cents=stake_cents,
        offered_decimal_odds=float(odds),
        potential_return_cents=potential_return,
        status=WagerStatus.OPEN,
        idempotency_key=idempotency_key,
    )
    session.add(wager)
    session.flush()

    session.add(
        LedgerEntry(
            account_id=account.id,
            entry_type=LedgerEntryType.WAGER_STAKE,
            amount_cents=-stake_cents,
            balance_after_cents=new_balance,
            reference_type="wager",
            reference_id=wager.id,
            memo=memo,
        )
    )
    session.flush()
    session.refresh(account)
    session.refresh(wager)
    return wager, account, False


def settle_wager_win(session: Session, wager: Wager) -> None:
    """Credit full quoted return (including stake); caller must only pass OPEN wagers."""
    if wager.status != WagerStatus.OPEN:
        raise ValueError("wager is not open")
    stmt = select(Account).where(Account.id == wager.account_id).with_for_update()
    account = session.scalar(stmt)
    if account is None:
        raise ValueError(f"account {wager.account_id} not found")
    payout = wager.potential_return_cents
    new_balance = account.balance_cents + payout
    account.balance_cents = new_balance
    session.add(
        LedgerEntry(
            account_id=account.id,
            entry_type=LedgerEntryType.WAGER_PAYOUT,
            amount_cents=payout,
            balance_after_cents=new_balance,
            reference_type="wager",
            reference_id=wager.id,
            memo=None,
        )
    )
    wager.status = WagerStatus.WON
    session.flush()


def settle_wager_loss(session: Session, wager: Wager) -> None:
    if wager.status != WagerStatus.OPEN:
        raise ValueError("wager is not open")
    wager.status = WagerStatus.LOST
    session.flush()


def settle_wager_void(session: Session, wager: Wager) -> None:
    """Refund stake for voided tickets (e.g. missing game or stat)."""
    if wager.status != WagerStatus.OPEN:
        raise ValueError("wager is not open")
    stmt = select(Account).where(Account.id == wager.account_id).with_for_update()
    account = session.scalar(stmt)
    if account is None:
        raise ValueError(f"account {wager.account_id} not found")
    refund = wager.stake_cents
    new_balance = account.balance_cents + refund
    account.balance_cents = new_balance
    session.add(
        LedgerEntry(
            account_id=account.id,
            entry_type=LedgerEntryType.WAGER_VOID,
            amount_cents=refund,
            balance_after_cents=new_balance,
            reference_type="wager",
            reference_id=wager.id,
            memo="Void — refund stake",
        )
    )
    wager.status = WagerStatus.VOID
    session.flush()
