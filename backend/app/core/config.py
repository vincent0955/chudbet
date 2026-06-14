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


BOOK_MARGIN_DEFAULT = 0.14
LINE_DRIFT_TOLERANCE_DEFAULT = 0.0


@lru_cache
def get_book_margin() -> float:
    """
    House book margin from CHUDBET_BOOK_MARGIN.
    Falls back to 0.14 when unset, invalid, or negative.
    """
    raw = os.getenv("CHUDBET_BOOK_MARGIN", "").strip()
    try:
        value = float(raw) if raw else BOOK_MARGIN_DEFAULT
    except ValueError:
        value = BOOK_MARGIN_DEFAULT
    return value if value >= 0 else BOOK_MARGIN_DEFAULT


@lru_cache
def get_line_drift_tolerance() -> float:
    """
    Maximum allowed absolute line drift from CHUDBET_LINE_DRIFT_TOLERANCE.
    Falls back to 0.0 when unset, invalid, or negative.
    """
    raw = os.getenv("CHUDBET_LINE_DRIFT_TOLERANCE", "").strip()
    try:
        value = float(raw) if raw else LINE_DRIFT_TOLERANCE_DEFAULT
    except ValueError:
        value = LINE_DRIFT_TOLERANCE_DEFAULT
    return value if value >= 0 else LINE_DRIFT_TOLERANCE_DEFAULT
