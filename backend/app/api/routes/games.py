from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import GamePropLinesBundle, GameRead
from app.db.models import Game
from app.db.session import get_db
from app.services.game_prop_lines import build_game_prop_lines_bundle

router = APIRouter(tags=["games"])


@router.get("/games/{game_id}/prop-lines", response_model=GamePropLinesBundle)
def get_game_prop_lines(game_id: int, db: Session = Depends(get_db)) -> GamePropLinesBundle:
    row = db.scalar(select(Game).where(Game.id == game_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return build_game_prop_lines_bundle(db, row)


@router.get("/games/{game_id}", response_model=GameRead)
def get_game(game_id: int, db: Session = Depends(get_db)) -> GameRead:
    row = db.scalar(select(Game).where(Game.id == game_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return GameRead.model_validate(row)


@router.get("/games", response_model=list[GameRead])
def list_games(
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
) -> list[GameRead]:
    stmt = (
        select(Game)
        .order_by(Game.game_date.desc(), Game.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.scalars(stmt).all()
    return [GameRead.model_validate(r) for r in rows]
