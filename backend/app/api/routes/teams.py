from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import TeamRead
from app.db.enums import Sport
from app.db.models import Team
from app.db.session import get_db

router = APIRouter(tags=["teams"])


@router.get("/teams", response_model=list[TeamRead])
def list_teams(
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
) -> list[TeamRead]:
    stmt = (
        select(Team)
        .where(Team.sport == Sport.NBA)
        .order_by(Team.name.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.scalars(stmt).all()
    return [TeamRead.model_validate(r) for r in rows]
