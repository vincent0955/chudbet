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

## Screenshots

![Home: upcoming games and bet slip](docs/Screenshot%202026-05-08%20154912.png)

![My Bets: open parlays](docs/Screenshot%202026-05-08%20155053.png)

![My Bets: settled parlay with leg results](docs/Screenshot%202026-05-08%20155111.png)
