from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.db.enums import LegDirection, ParlayMode, StatType

LegOutcomeUi = Literal["pending", "hit", "miss", "void"]


class LegIn(BaseModel):
    player_id: int = Field(ge=1)
    game_id: int | None = None
    stat_type: StatType
    line: float = Field(ge=-5, lt=200)
    direction: LegDirection


class ParlayCreate(BaseModel):
    mode: ParlayMode
    k_required: int | None = None
    wager_on_hit: bool = Field(
        default=True,
        description="True = bet parlay hits; False = anti-parlay (bet it does not hit).",
    )
    lookback_games: int = Field(default=15, ge=2, le=82)
    simulation_iterations: int = Field(default=100_000, ge=1_000, le=2_000_000)
    rng_seed: int | None = None
    legs: list[LegIn] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def mode_matches_k(self) -> Self:
        if self.mode == ParlayMode.STANDARD:
            if self.k_required is not None:
                raise ValueError("k_required must be omitted for standard parlays")
        else:
            if self.k_required is None:
                raise ValueError("k_required is required when mode is x_of_y")
            if not (1 <= self.k_required <= len(self.legs)):
                raise ValueError("k_required must be between 1 and len(legs)")
        return self


class ParlayLegRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    player_id: int
    game_id: int | None
    stat_type: StatType
    line: float
    direction: LegDirection
    leg_probability: float
    sort_order: int
    outcome: LegOutcomeUi | None = Field(
        default=None,
        description="pending / hit / miss / void from live stats vs line (null if not computed).",
    )
    player_full_name: str | None = Field(
        default=None,
        description="Set when Player relationship is loaded for display.",
    )


class ParlayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    mode: ParlayMode
    k_required: int | None
    total_legs: int
    p_hit: float | None
    wager_on_hit: bool
    fair_decimal_odds: float | None
    metadata_json: dict | None
    legs: list[ParlayLegRead]

    @computed_field
    @property
    def p_miss(self) -> float | None:
        if self.p_hit is None:
            return None
        return 1.0 - self.p_hit

    @computed_field
    @property
    def p_ticket(self) -> float | None:
        """Probability the placed wager wins (same as p_hit or p_miss by side)."""
        if self.p_hit is None:
            return None
        return self.p_hit if self.wager_on_hit else (1.0 - self.p_hit)
