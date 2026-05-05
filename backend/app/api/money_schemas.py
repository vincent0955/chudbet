"""Request/response schemas for accounts, ledger, and wagers."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.parlay_schemas import ParlayCreate, ParlayRead
from app.db.enums import LedgerEntryType, WagerStatus


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    balance_cents: int


class DepositBody(BaseModel):
    amount_cents: int = Field(ge=1, le=999_999_999_999)
    idempotency_key: str | None = Field(default=None, max_length=72)
    memo: str | None = Field(default=None, max_length=256)


class DepositResult(BaseModel):
    account: AccountRead
    ledger_entry_id: int
    duplicated: bool = Field(False, description="True when replaying the same idempotency_key.")


class WagerPlace(BaseModel):
    stake_cents: int = Field(ge=1, le=500_000_00)
    offered_decimal_odds: float | None = Field(
        default=None,
        gt=1,
        description="Book decimal payout odds (e.g. 2.05). Omit to use the model fair_decimal_odds on the ticket.",
    )
    idempotency_key: str | None = Field(default=None, max_length=72)
    parlay: ParlayCreate


class WagerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    account_id: int
    parlay_id: int
    stake_cents: int
    offered_decimal_odds: float
    potential_return_cents: int
    status: WagerStatus


class WagerCreated(BaseModel):
    wager: WagerRead
    account: AccountRead
    duplicated: bool = Field(False, description="True when replaying the same idempotency_key.")


class WagerDetail(WagerCreated):
    parlay: ParlayRead


class LedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    entry_type: LedgerEntryType
    amount_cents: int
    balance_after_cents: int
    reference_type: str | None
    reference_id: int | None
    memo: str | None
