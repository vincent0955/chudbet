from datetime import date

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
    status: str
    nba_game_id: str


class PlayerGameStatRead(BaseModel):
    """Single stat line with game identifiers for listing endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    nba_game_id: str
    game_date: date
    points: int
    rebounds: int
    assists: int
    minutes: float
