# ChudBet

ChutBet is a sportsbook that allows you to bet on your parlays to NOT hit or bet on only a certain amount of legs hitting.

## Layout

- `backend/` — FastAPI application
- `frontend/` — React (Vite + TypeScript) UI scaffold
- `infra/` — Reserved for future infrastructure (e.g. Terraform, k8s manifests)
- `docker-compose.yml` — Backend API + PostgreSQL

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- (Optional) Node.js 20+ and Python 3.12+ for local development without Docker for the full stack

## Run with Docker (recommended)

From the repository root:

```bash
docker compose up --build
```

- API: [http://localhost:8000/health](http://localhost:8000/health) should return `{"status":"ok"}`
- PostgreSQL runs in a container with a named volume for data

Default database credentials (override with environment variables if needed):

| Variable           | Default   |
| ------------------ | --------- |
| `POSTGRES_USER`    | `chudbet` |
| `POSTGRES_PASSWORD`| `chudbet` |
| `POSTGRES_DB`      | `chudbet` |

You can set `DATABASE_URL` on the backend instead of the individual `POSTGRES_*` variables if you prefer a single connection string.

The backend waits until Postgres passes its health check before starting (see `depends_on` in `docker-compose.yml`).

## Backend (local, without Docker)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

For a local DB, run Postgres via Docker only:

```bash
docker compose up postgres -d
```

Then set `POSTGRES_HOST=localhost` (and matching user/password/db) when running uvicorn.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Production build:

```bash
npm run build
```

The frontend is not wired into Docker Compose yet so it does not affect `docker compose up`.

## NBA data ingestion (`nba_api`)

The backend depends on [nba_api](https://github.com/swar/nba_api) (already listed in `backend/requirements.txt`). Ingestion runs as a **CLI**, not as a public HTTP route.

From `backend/` with `POSTGRES_*` or `DATABASE_URL` pointing at your database:

```bash
pip install -r requirements.txt
# Dev-sized sample: latest ~80 games + box scores (good for frontend testing)
python -m app.ingestion.cli --season 2025-26 --max-games 80 --recent-first
```

Useful flags:

| Flag | Meaning |
|------|---------|
| `--playoffs` | Use playoffs instead of regular season for the schedule query |
| `--max-games N` | Only process N games from LeagueGameFinder (default order: lowest `GAME_ID` first) |
| `--recent-first` | With `--max-games`, use the N games with the **latest** `GAME_DATE` (recommended for dev samples) |
| `--skip-stats` | Sync teams, rosters, and game rows only (no box-score calls) |
| `--scoreboard-days N` | Also upsert games from **ScoreboardV3** for **N** consecutive **Eastern** calendar days starting **today** (today + near-future slate; works with or without LeagueGameFinder) |
| `--skip-rosters` / `--skip-games` | Narrower partial runs (`--skip-games` skips finder only; pair with `--scoreboard-days` for a lightweight slate refresh) |

Omit `--max-games` to pull **all** games for the season (slow; many NBA HTTP calls).

**Upcoming games (e.g. next 3 days)** — merge scoreboard days after your usual finder pull, or refresh slate only:

```bash
python -m app.ingestion.cli --season 2025-26 --max-games 80 --recent-first --scoreboard-days 3 --skip-stats
python -m app.ingestion.cli --season 2025-26 --skip-games --skip-stats --scoreboard-days 3
```

The Docker image for the API **does not include** `app/ingestion/` (some Windows/Docker BuildKit setups fail to build when that folder is in the image context). Run the CLI **on your machine** with Postgres reachable on `localhost` (Compose publishes Postgres on port **5432**):

```powershell
cd backend
pip install -r requirements.txt
$env:POSTGRES_HOST = "localhost"
python -m app.ingestion.cli --season 2025-26 --max-games 80 --recent-first
```

The script spaces out HTTP calls (~0.65s) to reduce load on NBA.com.

### Schema changes and existing databases

Tables include stable NBA identifiers: `teams.nba_team_id`, `players.nba_player_id`, `games.nba_game_id`, plus a unique constraint on `(player_id, game_id)` for `player_game_stats`.

On startup and before ingestion, the backend runs **additive** Postgres DDL (`ADD COLUMN IF NOT EXISTS …`) via `app/db/migrate.py`. If every row in `teams` predates those columns (all `nba_team_id` null), related tables are cleared once so ingestion does not duplicate legacy rows.

For a completely clean slate you can still reset the volume:

```bash
docker compose down -v
docker compose up -d --build
```
