from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.db.enums import GameMarketType, GameSelection, LegDirection, ParlayMode, StatType

LegOutcomeUi = Literal["pending", "hit", "miss", "void"]


class LegIn(BaseModel):
    player_id: int = Field(ge=1)
    game_id: int | None = None
    stat_type: str = Field(min_length=1, max_length=16)
    line: float = Field(ge=-5, lt=200)
    direction: LegDirection


class GameLegIn(BaseModel):
    game_id: int = Field(ge=1)
    market_type: GameMarketType
    selection: GameSelection
    line: float | None = None
    odds_american: int = Field(ge=-10000, le=10000)

    @model_validator(mode="after")
    def market_selection_and_line(self) -> Self:
        if self.odds_american == 0:
            raise ValueError("odds_american cannot be 0")
        if self.market_type == GameMarketType.MONEYLINE:
            if self.selection not in (GameSelection.HOME, GameSelection.AWAY):
                raise ValueError("moneyline selection must be home/away")
            if self.line is not None:
                raise ValueError("moneyline line must be omitted")
            return self
        if self.market_type == GameMarketType.SPREAD:
            if self.selection not in (GameSelection.HOME, GameSelection.AWAY):
                raise ValueError("spread selection must be home/away")
            if self.line is None:
                raise ValueError("spread requires line")
            return self
        if self.selection not in (GameSelection.OVER, GameSelection.UNDER):
            raise ValueError("total selection must be over/under")
        if self.line is None:
            raise ValueError("total requires line")
        return self


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
    legs: list[LegIn] = Field(default_factory=list, max_length=16)
    game_legs: list[GameLegIn] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def mode_matches_k(self) -> Self:
        total_legs = len(self.legs) + len(self.game_legs)
        if total_legs < 1:
            raise ValueError("must include at least one leg")
        if self.mode == ParlayMode.STANDARD:
            if self.k_required is not None:
                raise ValueError("k_required must be omitted for standard parlays")
        else:
            if self.k_required is None:
                raise ValueError("k_required is required when mode is x_of_y")
            if not (1 <= self.k_required <= total_legs):
                raise ValueError("k_required must be between 1 and total leg count")
        return self


class ParlayLegRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    player_id: int
    player_nba_id: int | None = None
    player_team_nba_id: int | None = None
    player_mlb_id: int | None = None
    player_team_mlb_id: int | None = None
    game_id: int | None
    stat_type: str
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
    game_label: str | None = None
    game_home_team_name: str | None = None
    game_away_team_name: str | None = None
    game_home_score: int | None = None
    game_away_score: int | None = None
    game_date: date | None = None
    game_time_utc: datetime | None = None
    game_status: str | None = None
    stat_value: float | None = None


class ParlayGameLegRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    market_type: GameMarketType
    selection: GameSelection
    line: float | None
    odds_american: int
    leg_probability: float
    sort_order: int
    outcome: LegOutcomeUi | None = None
    game_label: str | None = None
    home_team_name: str | None = None
    away_team_name: str | None = None
    home_team_nba_id: int | None = None
    away_team_nba_id: int | None = None
    home_score: int | None = None
    away_score: int | None = None
    game_date: date | None = None
    game_time_utc: datetime | None = None
    game_status: str | None = None


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
    game_legs: list[ParlayGameLegRead] = Field(default_factory=list)
    stake_cents: int | None = None
    payout_cents: int | None = None

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

    @computed_field
    @property
    def payout_decimal_odds(self) -> float | None:
        """Server payout odds (fair odds reduced by house margin).

        Prefer the persisted margined value from `metadata_json`; fall back to
        `fair_decimal_odds` when no margined value is available.
        """
        if isinstance(self.metadata_json, dict):
            raw = self.metadata_json.get("payout_decimal_odds")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return float(raw)
        return self.fair_decimal_odds
