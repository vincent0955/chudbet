import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import accounts, auth, db_test, games, health, mlb, parlays, players, teams
from app.core.config import get_cors_origins
from app.db import models  # noqa: F401 — register models before create_all
from app.db.bootstrap import prepare_database_engine
from app.db.seed_demo import seed_demo_wallet_if_enabled
from app.db.session import check_db_connection, get_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    prepare_database_engine(engine)
    if check_db_connection():
        logger.info("Database connection ready")
        seed_demo_wallet_if_enabled()
    else:
        logger.warning("Database not reachable at startup (may still come up)")
    yield


app = FastAPI(title="Chudbet API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(db_test.router)
app.include_router(teams.router)
app.include_router(players.router)
app.include_router(games.router)
app.include_router(mlb.router)
app.include_router(parlays.router)
app.include_router(accounts.router)
app.include_router(auth.router)
