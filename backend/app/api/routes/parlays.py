from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.parlay_schemas import ParlayCreate, ParlayRead
from app.db.models import Parlay
from app.db.session import get_db
from app.parlay.service import create_parlay

router = APIRouter(tags=["parlays"])


@router.post("/parlays", response_model=ParlayRead, status_code=201)
def post_parlay(body: ParlayCreate, db: Session = Depends(get_db)) -> ParlayRead:
    try:
        parlay = create_parlay(db, body)
        parlay_id = parlay.id
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    parlay = db.scalar(
        select(Parlay)
        .where(Parlay.id == parlay_id)
        .options(selectinload(Parlay.legs))
    )
    return ParlayRead.model_validate(parlay)


@router.get("/parlays/{parlay_id}", response_model=ParlayRead)
def get_parlay(parlay_id: int, db: Session = Depends(get_db)) -> ParlayRead:
    parlay = db.scalar(
        select(Parlay)
        .where(Parlay.id == parlay_id)
        .options(selectinload(Parlay.legs))
    )
    if parlay is None:
        raise HTTPException(status_code=404, detail="Parlay not found")
    return ParlayRead.model_validate(parlay)
