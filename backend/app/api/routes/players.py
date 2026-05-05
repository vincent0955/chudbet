from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import PlayerGameStatRead, PlayerRead
from app.db.models import Game, Player, PlayerGameStat
from app.db.session import get_db

router = APIRouter(tags=["players"])


@router.get("/players", response_model=list[PlayerRead])
def list_players(
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
) -> list[PlayerRead]:
    stmt = (
        select(Player)
        .order_by(Player.full_name.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.scalars(stmt).all()
    return [PlayerRead.model_validate(r) for r in rows]


@router.get("/players/{player_id}/stats", response_model=list[PlayerGameStatRead])
def list_player_stats(
    player_id: int,
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
) -> list[PlayerGameStatRead]:
    player = db.scalar(select(Player).where(Player.id == player_id))
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    stmt = (
        select(PlayerGameStat, Game)
        .join(Game, PlayerGameStat.game_id == Game.id)
        .where(PlayerGameStat.player_id == player_id)
        .order_by(Game.game_date.desc(), Game.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).all()
    out: list[PlayerGameStatRead] = []
    for stat, game in rows:
        out.append(
            PlayerGameStatRead(
                id=stat.id,
                game_id=stat.game_id,
                nba_game_id=game.nba_game_id,
                game_date=game.game_date,
                points=stat.points,
                rebounds=stat.rebounds,
                assists=stat.assists,
                minutes=stat.minutes,
            )
        )
    return out
