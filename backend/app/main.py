import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import db_test, games, health, parlays, players, teams
from app.db import models  # noqa: F401 — register models before create_all
from app.db.base import Base
from app.db.migrate import ensure_postgres_schema
from app.db.session import check_db_connection, get_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    ensure_postgres_schema(engine)
    if check_db_connection():
        logger.info("Database connection ready")
    else:
        logger.warning("Database not reachable at startup (may still come up)")
    yield


app = FastAPI(title="Chudbet API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(db_test.router)
app.include_router(teams.router)
app.include_router(players.router)
app.include_router(games.router)
app.include_router(parlays.router)
