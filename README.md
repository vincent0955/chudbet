# ChudBet

ChudBet is a sportsbook that allows you to bet on your parlays to NOT hit or bet on only a certain amount of legs hitting.

## How it works

The **frontend** (React + Vite) talks to a **FastAPI** backend over JSON. In production the API runs on EC2 behind Caddy; the UI is hosted on Vercel.

The **backend** has three moving parts:

1. **API** (`backend/app/`) — serves teams, games, player props, and markets; prices parlays; manages auth and wallets. On startup it ensures the Postgres schema exists and applies lightweight migrations.

2. **Worker** (`backend/app/worker/`) — a separate process on a schedule. It ingests NBA scoreboard and box-score data into Postgres (`nba_api`), then grades open wagers against final stats (player props and game lines).

3. **Postgres** — stores the slate (teams, players, games, box scores), saved parlay snapshots, and a ledger-backed wallet per account.

**Placing a bet:** the client sends a parlay definition (player props and/or game legs, standard or X-of-Y, hit or anti). The API calculates leg probabilities from recent player stats (normal approximation) and implied odds for game legs, combines them into a ticket price, debits the stake from the account ledger, and stores an immutable parlay + wager row.

**Settlement:** when games finish, the worker compares each leg to box scores, resolves the ticket (all-hit, X-of-Y, or anti), and credits payouts or marks the wager lost/void. Balances change only through append-only ledger entries.

## Local Setup
**Prerequisites:** [Docker](https://docs.docker.com/get-docker/) with Compose, and [Node.js](https://nodejs.org/) 20+ for the frontend.

1. **API and database** — from the repo root:

   ```bash
   docker compose up --build
   ```

   When Postgres is healthy, the API should respond at [http://localhost:8000/health](http://localhost:8000/health) with `{"status":"ok"}`.

2. **Frontend** — in another terminal:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   Open the URL Vite prints (usually [http://localhost:5173](http://localhost:5173)).

## Tests

**Backend** (pytest; uses an in-memory SQLite database, so no Postgres or Docker is needed):

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

**Frontend unit tests** (Vitest):

```bash
cd frontend
npm install
npm test
```

**Frontend end-to-end / integration tests** (Playwright): 

```bash
cd frontend
npm install
npx playwright install chromium   # one-time browser download
npm run test:e2e
```

## CI/CD

GitHub Actions (`.github/workflows/ci-cd.yml`) runs all the test suites above on
every push and pull request to `main`. When tests pass on a push to `main`, it
assumes an AWS role via GitHub OIDC and uses AWS Systems Manager (SSM) to redeploy
the backend on EC2 (`git reset --hard`, `docker build`, then
`docker compose -f docker-compose.prod.yml up -d --no-build`) — no inbound SSH and no
static AWS keys.

## Screenshots

![Home: upcoming games and bet slip](docs/Screenshot%202026-05-08%20154912.png)

![My Bets: open parlays](docs/Screenshot%202026-05-08%20155053.png)

![My Bets: settled parlay with leg results](docs/Screenshot%202026-05-08%20155111.png)
