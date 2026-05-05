from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, Integer, JSON, func, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import ParlayMode

if TYPE_CHECKING:
    from app.db.models.parlay_leg import ParlayLeg
    from app.db.models.wager import Wager


class Parlay(Base):
    """A saved parlay configuration plus snapshot probability outputs."""

    __tablename__ = "parlays"

    __table_args__ = (
        CheckConstraint(
            "mode != 'x_of_y' OR (k_required IS NOT NULL AND k_required >= 1 "
            "AND k_required <= total_legs)",
            name="ck_parlay_x_of_y_k_valid",
        ),
        CheckConstraint(
            "mode != 'standard' OR k_required IS NULL",
            name="ck_parlay_standard_k_null",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    mode: Mapped[ParlayMode] = mapped_column(
        SQLEnum(ParlayMode, name="parlay_mode", native_enum=False, length=32),
        nullable=False,
    )
    k_required: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_legs: Mapped[int] = mapped_column(Integer, nullable=False)
    # DB column name kept as joint_probability for existing installs; value is always P(hit).
    p_hit: Mapped[float | None] = mapped_column(
        "joint_probability",
        Float,
        nullable=True,
    )
    wager_on_hit: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    # Fair decimal odds for the wager taken (hit or anti), i.e. 1 / P(ticket wins).
    fair_decimal_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    legs: Mapped[list["ParlayLeg"]] = relationship(
        "ParlayLeg",
        back_populates="parlay",
        cascade="all, delete-orphan",
        order_by="ParlayLeg.sort_order",
    )
    wager: Mapped["Wager | None"] = relationship(
        "Wager",
        back_populates="parlay",
        uselist=False,
    )
