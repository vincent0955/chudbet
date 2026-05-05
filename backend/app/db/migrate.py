"""Additive schema fixes for Postgres when metadata includes columns missing from an older DB."""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_postgres_schema(engine: Engine) -> None:
    """Add newer columns if absent (create_all does not ALTER existing tables)."""
    if engine.dialect.name != "postgresql":
        return

    statements = [
        "ALTER TABLE teams ADD COLUMN IF NOT EXISTS nba_team_id INTEGER",
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS nba_player_id INTEGER",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS nba_game_id VARCHAR(16)",
        (
            "ALTER TABLE parlays ADD COLUMN IF NOT EXISTS wager_on_hit BOOLEAN "
            "NOT NULL DEFAULT true"
        ),
    ]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))

        total = conn.execute(text("SELECT COUNT(*) FROM teams")).scalar_one()
        null_nba = conn.execute(
            text("SELECT COUNT(*) FROM teams WHERE nba_team_id IS NULL")
        ).scalar_one()
        if total > 0 and null_nba == total:
            conn.execute(text("DELETE FROM player_game_stats"))
            conn.execute(text("DELETE FROM games"))
            conn.execute(text("DELETE FROM players"))
            conn.execute(text("DELETE FROM teams"))
