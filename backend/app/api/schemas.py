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
    status: str
    nba_game_id: str


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
