from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    GameMarketsRead,
    MLBGamePropLinesBundle,
    MLBGameRead,
    MLBPlayerRead,
    MLBTeamRead,
)
from app.db.enums import Sport
from app.db.models import Game, Player, Team
from app.db.session import get_db
from app.mlb.game_markets import build_mlb_game_markets
from app.mlb.prop_lines import build_mlb_game_prop_lines_bundle

router = APIRouter(tags=["mlb"])


def _require_mlb_game(db: Session, game_id: int) -> Game:
    row = db.scalar(select(Game).where(Game.id == game_id))
    if row is None or row.sport != Sport.MLB:
        raise HTTPException(status_code=404, detail="Game not found")
    return row


@router.get("/mlb/games", response_model=list[MLBGameRead])
def list_mlb_games(
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
) -> list[MLBGameRead]:
    stmt = (
        select(Game)
        .where(Game.sport == Sport.MLB)
        .order_by(Game.game_time_utc.asc().nulls_last(), Game.game_date.asc(), Game.id.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.scalars(stmt).all()
    return [MLBGameRead.model_validate(r) for r in rows]


@router.get("/mlb/teams", response_model=list[MLBTeamRead])
def list_mlb_teams(
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
) -> list[MLBTeamRead]:
    stmt = (
        select(Team)
        .where(Team.sport == Sport.MLB)
        .order_by(Team.name.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.scalars(stmt).all()
    return [MLBTeamRead.model_validate(r) for r in rows]


@router.get("/mlb/players", response_model=list[MLBPlayerRead])
def list_mlb_players(
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
) -> list[MLBPlayerRead]:
    stmt = (
        select(Player)
        .where(Player.sport == Sport.MLB)
        .order_by(Player.full_name.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.scalars(stmt).all()
    return [MLBPlayerRead.model_validate(r) for r in rows]


@router.get("/mlb/games/{game_id}/markets", response_model=GameMarketsRead)
def get_mlb_game_markets(game_id: int, db: Session = Depends(get_db)) -> GameMarketsRead:
    row = _require_mlb_game(db, game_id)
    return build_mlb_game_markets(db, row)


@router.get("/mlb/games/{game_id}/prop-lines", response_model=MLBGamePropLinesBundle)
def get_mlb_game_prop_lines(
    game_id: int, db: Session = Depends(get_db)
) -> MLBGamePropLinesBundle:
    row = _require_mlb_game(db, game_id)
    return build_mlb_game_prop_lines_bundle(db, row)
