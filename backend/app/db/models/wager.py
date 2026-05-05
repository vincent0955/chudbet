from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import WagerStatus

if TYPE_CHECKING:
    from app.db.models.account import Account
    from app.db.models.parlay import Parlay


class Wager(Base):
    """Financial ticket tied to a single saved parlay snapshot."""

    __tablename__ = "wagers"

    __table_args__ = (
        UniqueConstraint("parlay_id", name="uq_wagers_parlay_id"),
        CheckConstraint("stake_cents > 0", name="ck_wagers_stake_positive"),
        CheckConstraint("potential_return_cents >= 0", name="ck_wagers_return_nonneg"),
        CheckConstraint("offered_decimal_odds > 1", name="ck_wagers_odds_gt_one"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    parlay_id: Mapped[int] = mapped_column(
        ForeignKey("parlays.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stake_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    offered_decimal_odds: Mapped[float] = mapped_column(Float, nullable=False)
    potential_return_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[WagerStatus] = mapped_column(
        SQLEnum(WagerStatus, name="wager_status", native_enum=False, length=32),
        nullable=False,
        default=WagerStatus.OPEN,
        server_default=WagerStatus.OPEN.value,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(72), nullable=True, unique=True)

    account: Mapped["Account"] = relationship("Account", back_populates="wagers")
    parlay: Mapped["Parlay"] = relationship("Parlay", back_populates="wager")
