from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Team
from app.db.session import get_db

router = APIRouter(tags=["db"])


@router.get("/db-test")
def db_test(db: Session = Depends(get_db)) -> dict[str, str | int]:
    """Verify DB connectivity and session wiring with a trivial query."""
    count = db.scalar(select(func.count()).select_from(Team))
    if count is None:
        count = 0
    return {"status": "ok", "teams_count": count}
