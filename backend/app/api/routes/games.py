from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import GameRead
from app.db.models import Game
from app.db.session import get_db

router = APIRouter(tags=["games"])


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
