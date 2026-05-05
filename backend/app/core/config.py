import os
from functools import lru_cache


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
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
