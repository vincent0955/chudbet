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
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS game_time_utc TIMESTAMPTZ",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS home_score INTEGER",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS away_score INTEGER",
        (
            "CREATE TABLE IF NOT EXISTS parlay_game_legs ("
            "id SERIAL PRIMARY KEY, "
            "parlay_id INTEGER NOT NULL REFERENCES parlays(id) ON DELETE CASCADE, "
            "game_id INTEGER NOT NULL REFERENCES games(id), "
            "market_type VARCHAR(16) NOT NULL, "
            "selection VARCHAR(16) NOT NULL, "
            "line DOUBLE PRECISION NULL, "
            "odds_american INTEGER NOT NULL, "
            "leg_probability DOUBLE PRECISION NOT NULL, "
            "sort_order INTEGER NOT NULL, "
            "CONSTRAINT uq_parlay_game_leg_order UNIQUE(parlay_id, sort_order)"
            ")"
        ),
        (
            "ALTER TABLE parlays ADD COLUMN IF NOT EXISTS wager_on_hit BOOLEAN "
            "NOT NULL DEFAULT true"
        ),
        (
            "CREATE TABLE IF NOT EXISTS users ("
            "id SERIAL PRIMARY KEY, "
            "email VARCHAR(320) NOT NULL UNIQUE, "
            "username VARCHAR(64) NOT NULL UNIQUE, "
            "password_hash VARCHAR(512) NOT NULL, "
            "is_guest BOOLEAN NOT NULL DEFAULT false, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ),
        "CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(64)",
        "UPDATE users SET username = COALESCE(username, CONCAT('user', id)) WHERE username IS NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)",
        "ALTER TABLE users ALTER COLUMN username SET NOT NULL",
        (
            "CREATE TABLE IF NOT EXISTS user_sessions ("
            "id SERIAL PRIMARY KEY, "
            "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "token_hash VARCHAR(128) NOT NULL UNIQUE, "
            "user_agent VARCHAR(512) NULL, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "expires_at TIMESTAMPTZ NOT NULL, "
            "revoked_at TIMESTAMPTZ NULL"
            ")"
        ),
        "CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_sessions_token_hash ON user_sessions (token_hash)",
        "CREATE INDEX IF NOT EXISTS ix_user_sessions_expires_at ON user_sessions (expires_at)",
        "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_accounts_user_id ON accounts (user_id)",
        "ALTER TABLE parlay_legs ADD COLUMN IF NOT EXISTS outcome_status VARCHAR(16) NOT NULL DEFAULT 'pending'",
        "ALTER TABLE parlay_game_legs ADD COLUMN IF NOT EXISTS outcome_status VARCHAR(16) NOT NULL DEFAULT 'pending'",
        # --- MLB / multi-sport additive migration (Req 1.6, 1.7) ---
        # 1. sport discriminator. NOT NULL DEFAULT 'NBA' backfills every existing
        #    (legacy NBA) row to 'NBA'.
        "ALTER TABLE teams ADD COLUMN IF NOT EXISTS sport VARCHAR(8) NOT NULL DEFAULT 'NBA'",
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS sport VARCHAR(8) NOT NULL DEFAULT 'NBA'",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS sport VARCHAR(8) NOT NULL DEFAULT 'NBA'",
        # 2. native MLB id columns + descriptive columns (all nullable; types match ORM).
        "ALTER TABLE teams ADD COLUMN IF NOT EXISTS mlb_team_id INTEGER",
        "ALTER TABLE teams ADD COLUMN IF NOT EXISTS abbreviation VARCHAR(16)",
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS mlb_player_id INTEGER",
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS primary_position VARCHAR(32)",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS mlb_game_id VARCHAR(16)",
        # 3. Drop the old GLOBAL uniques on the native NBA ids. The prior ORM declared
        #    these columns unique=True, index=True, so create_all produced unique indexes
        #    named ix_<table>_<col>. Also defensively drop any default-named unique
        #    table constraints in case an older schema used those.
        "DROP INDEX IF EXISTS ix_teams_nba_team_id",
        "DROP INDEX IF EXISTS ix_players_nba_player_id",
        "DROP INDEX IF EXISTS ix_games_nba_game_id",
        "ALTER TABLE teams DROP CONSTRAINT IF EXISTS teams_nba_team_id_key",
        "ALTER TABLE players DROP CONSTRAINT IF EXISTS players_nba_player_id_key",
        "ALTER TABLE games DROP CONSTRAINT IF EXISTS games_nba_game_id_key",
        # 4. Make native NBA id columns nullable (DROP NOT NULL is idempotent).
        "ALTER TABLE teams ALTER COLUMN nba_team_id DROP NOT NULL",
        "ALTER TABLE players ALTER COLUMN nba_player_id DROP NOT NULL",
        "ALTER TABLE games ALTER COLUMN nba_game_id DROP NOT NULL",
        # Recreate the plain (non-unique) lookup indexes to match ORM index=True.
        "CREATE INDEX IF NOT EXISTS ix_teams_nba_team_id ON teams (nba_team_id)",
        "CREATE INDEX IF NOT EXISTS ix_players_nba_player_id ON players (nba_player_id)",
        "CREATE INDEX IF NOT EXISTS ix_games_nba_game_id ON games (nba_game_id)",
        "CREATE INDEX IF NOT EXISTS ix_teams_mlb_team_id ON teams (mlb_team_id)",
        "CREATE INDEX IF NOT EXISTS ix_players_mlb_player_id ON players (mlb_player_id)",
        "CREATE INDEX IF NOT EXISTS ix_games_mlb_game_id ON games (mlb_game_id)",
        # 5. Six per-sport PARTIAL unique indexes (names match ORM __table_args__).
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_teams_nba_id ON teams (nba_team_id) "
        "WHERE nba_team_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_teams_mlb_id ON teams (mlb_team_id) "
        "WHERE mlb_team_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_players_nba_id ON players (nba_player_id) "
        "WHERE nba_player_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_players_mlb_id ON players (mlb_player_id) "
        "WHERE mlb_player_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_games_nba_id ON games (nba_game_id) "
        "WHERE nba_game_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_games_mlb_id ON games (mlb_game_id) "
        "WHERE mlb_game_id IS NOT NULL",
        # 7. Isolated MLB per-game stats table (names match ORM MLBPlayerGameStat).
        (
            "CREATE TABLE IF NOT EXISTS mlb_player_game_stats ("
            "id SERIAL PRIMARY KEY, "
            "player_id INTEGER NOT NULL REFERENCES players(id), "
            "game_id INTEGER NOT NULL REFERENCES games(id), "
            "hits INTEGER NOT NULL DEFAULT 0, "
            "total_bases INTEGER NOT NULL DEFAULT 0, "
            "rbi INTEGER NOT NULL DEFAULT 0, "
            "runs INTEGER NOT NULL DEFAULT 0, "
            "strikeouts_pitcher INTEGER NOT NULL DEFAULT 0, "
            "CONSTRAINT uq_mlb_player_game_stat UNIQUE(player_id, game_id), "
            "CONSTRAINT ck_mlb_player_game_stat_hits_nonneg CHECK (hits >= 0), "
            "CONSTRAINT ck_mlb_player_game_stat_total_bases_nonneg CHECK (total_bases >= 0), "
            "CONSTRAINT ck_mlb_player_game_stat_rbi_nonneg CHECK (rbi >= 0), "
            "CONSTRAINT ck_mlb_player_game_stat_runs_nonneg CHECK (runs >= 0), "
            "CONSTRAINT ck_mlb_player_game_stat_strikeouts_pitcher_nonneg "
            "CHECK (strikeouts_pitcher >= 0)"
            ")"
        ),
        "CREATE INDEX IF NOT EXISTS ix_mlb_player_game_stats_player_id "
        "ON mlb_player_game_stats (player_id)",
        "CREATE INDEX IF NOT EXISTS ix_mlb_player_game_stats_game_id "
        "ON mlb_player_game_stats (game_id)",
    ]

    # 6. The three sport/native-id CHECK constraints (names match ORM). Postgres has no
    #    ADD CONSTRAINT IF NOT EXISTS for CHECKs, so guard each with pg_constraint. These
    #    run AFTER the bootstrap wipe below so a legacy all-NULL NBA dataset is cleared
    #    first and cannot fail constraint validation.
    check_constraints = [
        (
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_teams_sport_native_id') THEN "
            "ALTER TABLE teams ADD CONSTRAINT ck_teams_sport_native_id CHECK ("
            "(sport = 'NBA' AND nba_team_id IS NOT NULL AND mlb_team_id IS NULL) "
            "OR (sport = 'MLB' AND mlb_team_id IS NOT NULL AND nba_team_id IS NULL)); "
            "END IF; END $$;"
        ),
        (
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_players_sport_native_id') THEN "
            "ALTER TABLE players ADD CONSTRAINT ck_players_sport_native_id CHECK ("
            "(sport = 'NBA' AND nba_player_id IS NOT NULL AND mlb_player_id IS NULL) "
            "OR (sport = 'MLB' AND mlb_player_id IS NOT NULL AND nba_player_id IS NULL)); "
            "END IF; END $$;"
        ),
        (
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_games_sport_native_id') THEN "
            "ALTER TABLE games ADD CONSTRAINT ck_games_sport_native_id CHECK ("
            "(sport = 'NBA' AND nba_game_id IS NOT NULL AND mlb_game_id IS NULL) "
            "OR (sport = 'MLB' AND mlb_game_id IS NOT NULL AND nba_game_id IS NULL)); "
            "END IF; END $$;"
        ),
    ]

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))

        # 8. Destructive bootstrap wipe — scoped to sport='NBA' ONLY.
        # Original intent: a legacy NBA dataset that predates the nba_team_id column has
        # all-NULL native ids; wipe it so a fresh ingest can repopulate. We now scope both
        # the trigger condition and the deletes to sport='NBA' so MLB rows (which
        # legitimately carry NULL nba_team_id) are NEVER detected by or swept by the wipe.
        nba_total = conn.execute(
            text("SELECT COUNT(*) FROM teams WHERE sport = 'NBA'")
        ).scalar_one()
        nba_with_id = conn.execute(
            text("SELECT COUNT(*) FROM teams WHERE sport = 'NBA' AND nba_team_id IS NOT NULL")
        ).scalar_one()
        if nba_total > 0 and nba_with_id == 0:
            conn.execute(
                text(
                    "DELETE FROM player_game_stats WHERE "
                    "game_id IN (SELECT id FROM games WHERE sport = 'NBA') "
                    "OR player_id IN (SELECT id FROM players WHERE sport = 'NBA')"
                )
            )
            conn.execute(text("DELETE FROM games WHERE sport = 'NBA'"))
            conn.execute(text("DELETE FROM players WHERE sport = 'NBA'"))
            conn.execute(text("DELETE FROM teams WHERE sport = 'NBA'"))

        # Add the sport/native-id CHECK constraints after the wipe so legacy NBA rows
        # (now removed) cannot fail validation.
        for stmt in check_constraints:
            conn.execute(text(stmt))
