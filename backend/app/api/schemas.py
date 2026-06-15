from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    nba_team_id: int


class PlayerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    team_id: int
    nba_player_id: int


class GameRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    home_team_id: int
    away_team_id: int
    game_date: date
    game_time_utc: datetime | None = None
    home_score: int | None = None
    away_score: int | None = None
    status: str
    sport: str | None = None
    nba_game_id: str | None = None
    mlb_game_id: str | None = None


class PlayerGameStatRead(BaseModel):
    """Single stat line with game identifiers for listing endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    nba_game_id: str
    game_date: date
    game_time_utc: datetime | None = None
    game_status: str
    points: int
    rebounds: int
    assists: int
    minutes: float


class PlayerPropLinesRead(BaseModel):
    """Per-player projected PTS/REB/AST lines for one game (rolling avg — see bundle metadata)."""

    id: int
    full_name: str
    team_id: int
    team_name: str
    team_nba_id: int | None = None
    nba_player_id: int
    sample_size: int
    pts_line: float | None = None
    reb_line: float | None = None
    ast_line: float | None = None
    pts_over_american: str
    pts_under_american: str
    reb_over_american: str
    reb_under_american: str
    ast_over_american: str
    ast_under_american: str


class GamePropLinesBundle(BaseModel):
    game: GameRead
    lookback: int
    min_samples: int
    players: list[PlayerPropLinesRead]


class MLBTeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    mlb_team_id: int | None = None
    abbreviation: str | None = None


class MLBPlayerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    team_id: int
    mlb_player_id: int | None = None
    primary_position: str | None = None


class MLBGameRead(BaseModel):
    """MLB game view (carries ``mlb_game_id`` instead of NBA's ``nba_game_id``)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    home_team_id: int
    away_team_id: int
    game_date: date
    game_time_utc: datetime | None = None
    home_score: int | None = None
    away_score: int | None = None
    status: str
    mlb_game_id: str | None = None


class MLBPropStatLineRead(BaseModel):
    """One offered MLB player-prop stat: line plus over/under American odds."""

    stat_type: str
    line: float
    over_american: str
    under_american: str


class MLBPlayerPropLinesRead(BaseModel):
    """Per-player MLB prop lines for one game (only offered stats are included)."""

    id: int
    full_name: str
    team_id: int
    team_name: str
    mlb_team_id: int | None = None
    mlb_player_id: int | None = None
    primary_position: str | None = None
    sample_size: int
    stat_lines: list[MLBPropStatLineRead]


class MLBGamePropLinesBundle(BaseModel):
    game: MLBGameRead
    lookback_days: int
    min_samples: int
    players: list[MLBPlayerPropLinesRead]


class GameMoneylineMarketRead(BaseModel):
    home_american: str
    away_american: str


class GameSpreadMarketRead(BaseModel):
    home_line: float
    home_american: str
    away_line: float
    away_american: str


class GameTotalMarketRead(BaseModel):
    line: float
    over_american: str
    under_american: str


class GameMarketsRead(BaseModel):
    game: GameRead
    lookback: int
    sample_games_home: int
    sample_games_away: int
    moneyline: GameMoneylineMarketRead
    spread: GameSpreadMarketRead
    total: GameTotalMarketRead


class AuthSignupBody(BaseModel):
    email: str
    username: str
    password: str


class AuthLoginBody(BaseModel):
    email: str
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str
    is_guest: bool
    created_at: datetime


class AuthMeRead(BaseModel):
    user: UserRead
    account_id: int
    balance_cents: int
