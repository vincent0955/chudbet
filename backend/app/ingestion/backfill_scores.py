"""Backfill home/away scores for games that are already final.

This is intentionally simple and functional-first:
- only fills `Game.home_score` / `Game.away_score` when missing
- uses nba_api boxscore team_stats (v3, fallback v2)
- avoids re-ingesting player stats (fast + quiet)
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Game, Team
from app.ingestion.nba_sync import NBA_CALENDAR_TZ, _pause, _parse_score
from nba_api.stats.endpoints import scoreboardv3

logger = logging.getLogger(__name__)


def backfill_missing_final_game_scores(session: Session, *, commit_every: int = 25) -> dict[str, int]:
    """
    Fill `home_score` / `away_score` for FINAL games missing them.

    Uses ScoreboardV3 by `game_date` (fast, avoids per-game boxscore calls that can hang).
    """
    counts = {"dates_seen": 0, "games_seen": 0, "filled": 0, "skipped_no_match": 0}

    games = session.scalars(select(Game).where(Game.status.ilike("%final%"), Game.home_score.is_(None))).all()
    by_date: dict[date, list[Game]] = {}
    for g in games:
        by_date.setdefault(g.game_date, []).append(g)

    dates = sorted(by_date.keys())
    logger.info("Backfill scores: %d final games missing scores across %d date(s)", len(games), len(dates))

    for di, d in enumerate(dates, start=1):
        counts["dates_seen"] += 1
        _pause()
        sb = scoreboardv3.ScoreboardV3(game_date=d.isoformat())
        dfs = sb.get_data_frames()
        if len(dfs) < 3 or dfs[1] is None or dfs[1].empty or dfs[2] is None or dfs[2].empty:
            continue

        teams_lines = dfs[2].copy()
        teams_lines["gameId"] = teams_lines["gameId"].astype(str).str.strip()

        # Build map nba_game_id -> {nba_team_id -> score}
        score_map: dict[str, dict[int, int]] = {}
        for _, row in teams_lines.iterrows():
            gid = str(row.get("gameId") or "").strip()
            tid = row.get("teamId")
            if not gid or tid is None:
                continue
            nba_tid = int(tid)
            pts = _parse_score(row.get("score"))
            if pts is None:
                continue
            score_map.setdefault(gid, {})[nba_tid] = pts

        for g in by_date[d]:
            counts["games_seen"] += 1
            pts_by_team = score_map.get(str(g.nba_game_id).strip())
            if not pts_by_team:
                counts["skipped_no_match"] += 1
                continue
            home_team = session.get(Team, g.home_team_id)
            away_team = session.get(Team, g.away_team_id)
            if home_team is not None:
                g.home_score = pts_by_team.get(home_team.nba_team_id)
            if away_team is not None:
                g.away_score = pts_by_team.get(away_team.nba_team_id)
            if g.home_score is not None and g.away_score is not None:
                counts["filled"] += 1

        if commit_every > 0 and di % commit_every == 0:
            session.commit()
            logger.info("Backfill progress: %d/%d date(s)", di, len(dates))

    session.commit()
    logger.info("Backfill scores done: %s", counts)
    return counts

