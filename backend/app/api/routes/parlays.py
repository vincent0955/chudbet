from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.parlay_schemas import ParlayCreate, ParlayRead
from app.db.models import Parlay
from app.db.session import get_db
from app.parlay.display import parlay_detail_load_options, parlay_read_with_leg_display
from app.parlay.pricing import PricingError
from app.parlay.service import create_parlay

router = APIRouter(tags=["parlays"])


@router.post("/parlays", response_model=ParlayRead, status_code=201)
def post_parlay(body: ParlayCreate, db: Session = Depends(get_db)) -> ParlayRead:
    try:
        parlay = create_parlay(db, body)
        parlay_id = parlay.id
        db.commit()
    except PricingError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    parlay = db.scalar(
        select(Parlay)
        .where(Parlay.id == parlay_id)
        .options(*parlay_detail_load_options()),
    )
    if parlay is None:
        raise HTTPException(status_code=404, detail="Parlay not found")
    return parlay_read_with_leg_display(db, parlay)


@router.get("/parlays/{parlay_id}", response_model=ParlayRead)
def get_parlay(parlay_id: int, db: Session = Depends(get_db)) -> ParlayRead:
    parlay = db.scalar(
        select(Parlay)
        .where(Parlay.id == parlay_id)
        .options(*parlay_detail_load_options()),
    )
    if parlay is None:
        raise HTTPException(status_code=404, detail="Parlay not found")
    return parlay_read_with_leg_display(db, parlay)
