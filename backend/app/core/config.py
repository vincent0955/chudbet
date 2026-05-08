import os
from functools import lru_cache
from urllib.parse import quote_plus


@lru_cache
def get_database_url() -> str:
    """Build SQLAlchemy database URL from environment (Docker-friendly)."""
    if url := os.getenv("DATABASE_URL"):
        return url
    user = os.getenv("POSTGRES_USER", "chudbet")
    password = os.getenv("POSTGRES_PASSWORD", "chudbet")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "chudbet")
    u = quote_plus(user, safe="")
    p = quote_plus(password, safe="")
    return f"postgresql+psycopg2://{u}:{p}@{host}:{port}/{db}"


@lru_cache
def get_cors_origins() -> list[str]:
    """
    Parse comma-separated CORS origins from CHUDBET_CORS_ORIGINS.
    Falls back to local development origins when unset.
    """
    raw = os.getenv("CHUDBET_CORS_ORIGINS", "").strip()
    if raw:
        origins = [origin.strip().rstrip("/") for origin in raw.split(",")]
        return [origin for origin in origins if origin]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
