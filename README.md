# ChudBet

ChudBet is a sportsbook that allows you to bet on your parlays to NOT hit or bet on only a certain amount of legs hitting.

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

**Frontend end-to-end / integration tests** (Playwright): these run the real Vite
frontend and stub the backend API at the network layer, so they need neither the
backend nor Postgres. The first run downloads a browser.

```bash
cd frontend
npm install
npx playwright install chromium   # one-time browser download
npm run test:e2e
```

The E2E suite covers the main features: the home schedule, auth (guest login /
signup / logout), wallet deposits, the game prop board, building and placing a
parlay end to end, and the My Bets open/settled views.

## Screenshots

![Home: upcoming games and bet slip](docs/Screenshot%202026-05-08%20154912.png)

![My Bets: open parlays](docs/Screenshot%202026-05-08%20155053.png)

![My Bets: settled parlay with leg results](docs/Screenshot%202026-05-08%20155111.png)
