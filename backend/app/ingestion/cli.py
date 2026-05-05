"""CLI entrypoint for NBA stats ingestion."""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db import models  # noqa: F401 — register models for create_all
from app.db.migrate import ensure_postgres_schema
from app.db.session import get_engine
from app.ingestion.nba_sync import run_full_ingest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Load NBA teams, rosters, games, and box scores into Postgres via nba_api. "
            "Runs schema bootstrap (including empty parlays / parlay_legs tables); "
            "ingestion only fills core warehouse tables."
        ),
    )
    parser.add_argument(
        "--season",
        default="2025-26",
        help="NBA season string, e.g. 2025-26 (default: %(default)s)",
    )
    parser.add_argument(
        "--playoffs",
        action="store_true",
        help="Use Playoffs instead of Regular Season for LeagueGameFinder.",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=None,
        metavar="N",
        help="Limit to the first N games (after sorting by GAME_ID) for faster trial runs.",
    )
    parser.add_argument(
        "--skip-rosters",
        action="store_true",
        help="Only sync teams (no CommonTeamRoster player upserts).",
    )
    parser.add_argument(
        "--skip-games",
        action="store_true",
        help="Stop after rosters (no LeagueGameFinder games).",
    )
    parser.add_argument(
        "--skip-stats",
        action="store_true",
        help="Sync teams/rosters/games but skip per-game box scores.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    ensure_postgres_schema(engine)

    regular_only = not args.playoffs

    with Session(engine) as session:
        run_full_ingest(
            session,
            season=args.season,
            regular_only=regular_only,
            max_games=args.max_games,
            skip_rosters=args.skip_rosters,
            skip_games=args.skip_games,
            skip_stats=args.skip_stats,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
