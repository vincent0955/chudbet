"""Anonymous accounts (wallets): balance, deposits, wagers."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.money_schemas import (
    AccountRead,
    DepositBody,
    DepositResult,
    LedgerEntryRead,
    WagerDetail,
    WagerPlace,
    WagerRead,
)
from app.api.auth import get_current_user
from app.db.models import Account, LedgerEntry, Parlay, Wager
from app.parlay.display import parlay_detail_load_options, parlay_read_with_leg_display
from app.parlay.pricing import PricingError
from app.db.session import get_db
from app.services import money
from app.db.models import User

router = APIRouter(prefix="/accounts", tags=["accounts"])


Db = Annotated[Session, Depends(get_db)]


def _require_account_access(db: Session, account_id: int, user: User) -> Account:
    row = db.get(Account, account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if row.user_id is None or row.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return row


@router.post("", response_model=AccountRead, status_code=201)
def post_account(db: Db) -> AccountRead:
    row = money.create_account(db)
    db.commit()
    db.refresh(row)
    return AccountRead.model_validate(row)


@router.get("/{account_id}", response_model=AccountRead)
def get_account(account_id: int, db: Db, user: User = Depends(get_current_user)) -> AccountRead:
    row = _require_account_access(db, account_id, user)
    return AccountRead.model_validate(row)


@router.post("/{account_id}/deposit", response_model=DepositResult)
def post_deposit(account_id: int, body: DepositBody, db: Db, user: User = Depends(get_current_user)) -> DepositResult:
    _require_account_access(db, account_id, user)
    try:
        account, entry, duplicated = money.deposit(
            db,
            account_id,
            amount_cents=body.amount_cents,
            idempotency_key=body.idempotency_key,
            memo=body.memo,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(account)
    return DepositResult(
        account=AccountRead.model_validate(account),
        ledger_entry_id=entry.id,
        duplicated=duplicated,
    )


@router.post("/{account_id}/wagers", response_model=WagerDetail)
def post_wager(account_id: int, body: WagerPlace, db: Db, user: User = Depends(get_current_user)) -> WagerDetail:
    _require_account_access(db, account_id, user)
    try:
        wager, account, duplicated = money.place_wager(
            db,
            account_id,
            stake_cents=body.stake_cents,
            offered_decimal_odds=body.offered_decimal_odds,
            parlay_body=body.parlay,
            idempotency_key=body.idempotency_key,
        )
        db.commit()
    except money.InsufficientBalanceError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Insufficient balance") from None
    except PricingError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    parlay = db.scalar(
        select(Parlay)
        .where(Parlay.id == wager.parlay_id)
        .options(*parlay_detail_load_options()),
    )
    if parlay is None:
        raise HTTPException(status_code=500, detail="Parlay missing after wager create")
    db.refresh(account)
    db.refresh(wager)
    return WagerDetail(
        wager=WagerRead.model_validate(wager),
        account=AccountRead.model_validate(account),
        parlay=parlay_read_with_leg_display(db, parlay),
        duplicated=duplicated,
    )


@router.get("/{account_id}/wagers", response_model=list[WagerRead])
def list_wagers(
    account_id: int,
    db: Db,
    user: User = Depends(get_current_user),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[WagerRead]:
    _require_account_access(db, account_id, user)
    rows = db.scalars(
        select(Wager)
        .where(Wager.account_id == account_id)
        .order_by(Wager.created_at.desc())
        .limit(limit),
    ).all()
    return [WagerRead.model_validate(r) for r in rows]


@router.get("/{account_id}/ledger", response_model=list[LedgerEntryRead])
def list_ledger(
    account_id: int,
    db: Db,
    user: User = Depends(get_current_user),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[LedgerEntryRead]:
    _require_account_access(db, account_id, user)
    rows = db.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.account_id == account_id)
        .order_by(LedgerEntry.created_at.desc())
        .limit(limit),
    ).all()
    return [LedgerEntryRead.model_validate(r) for r in rows]


@router.get("/{account_id}/wagers/{wager_id}", response_model=WagerDetail)
def get_wager(account_id: int, wager_id: int, db: Db, user: User = Depends(get_current_user)) -> WagerDetail:
    _require_account_access(db, account_id, user)
    wager = db.get(Wager, wager_id)
    if wager is None or wager.account_id != account_id:
        raise HTTPException(status_code=404, detail="Wager not found")
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    parlay = db.scalar(
        select(Parlay).where(Parlay.id == wager.parlay_id).options(*parlay_detail_load_options()),
    )
    if parlay is None:
        raise HTTPException(status_code=500, detail="Parlay missing for wager")
    return WagerDetail(
        wager=WagerRead.model_validate(wager),
        account=AccountRead.model_validate(account),
        parlay=parlay_read_with_leg_display(db, parlay),
        duplicated=False,
    )
