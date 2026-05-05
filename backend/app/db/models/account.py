from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.ledger_entry import LedgerEntry
    from app.db.models.wager import Wager


class Account(Base):
    """Anonymous or future-authenticated wallet; balance updated only via ledger postings."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    balance_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry",
        back_populates="account",
    )
    wagers: Mapped[list["Wager"]] = relationship("Wager", back_populates="account")
