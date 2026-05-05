"""Sync NBA stats into warehouse tables: teams, players, games, player_game_stats.

Parlay tables (`parlays`, `parlay_legs`) are never written here—they are populated by
the application when users build parlays.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import pandas as pd
from nba_api.stats.endpoints import (
    boxscoresummaryv3,
    boxscoretraditionalv2,
    boxscoretraditionalv3,
    commonteamroster,
    leaguegamefinder,
)
from nba_api.stats.static import teams as static_teams
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Game, Player, PlayerGameStat, Team
from app.ingestion.minutes import normalize_stat_int, parse_minutes

logger = logging.getLogger(__name__)

REQUEST_PAUSE_SEC = 0.65


def _pause() -> None:
    time.sleep(REQUEST_PAUSE_SEC)


def sync_teams(session: Session) -> dict[int, Team]:
    """Upsert all NBA teams from static data. Returns map nba_team_id -> Team."""
    rows = static_teams.get_teams()
    by_nba: dict[int, Team] = {}
    for row in rows:
        nba_id = int(row["id"])
        name = str(row["full_name"])
        team = session.scalar(select(Team).where(Team.nba_team_id == nba_id))
        if team is None:
            team = Team(nba_team_id=nba_id, name=name)
            session.add(team)
        else:
            team.name = name
        by_nba[nba_id] = team
    session.flush()
    logger.info("Synced %d teams", len(by_nba))
    return by_nba


def sync_rosters(session: Session, season: str, teams_by_nba: dict[int, Team]) -> None:
    """Upsert players from each team's CommonTeamRoster for the season."""
    count = 0
    for nba_tid, team in teams_by_nba.items():
        _pause()
        roster = commonteamroster.CommonTeamRoster(team_id=nba_tid, season=season)
        df = roster.common_team_roster.get_data_frame()
        for _, row in df.iterrows():
            pid = int(row["PLAYER_ID"])
            full_name = str(row["PLAYER"]).strip()
            existing = session.scalar(select(Player).where(Player.nba_player_id == pid))
            if existing is None:
                session.add(
                    Player(
                        nba_player_id=pid,
                        full_name=full_name,
                        team_id=team.id,
                    )
                )
            else:
                existing.full_name = full_name
                existing.team_id = team.id
            count += 1
        logger.debug("Roster team %s: %d players", team.name, len(df))
    session.flush()
    logger.info("Upserted roster rows (total iterations): %d", count)


def _season_type_arg(regular_only: bool) -> str:
    return "Regular Season" if regular_only else "Playoffs"


def load_season_game_rows(season: str, regular_only: bool) -> pd.DataFrame:
    _pause()
    lg = leaguegamefinder.LeagueGameFinder(
        season_nullable=season,
        season_type_nullable=_season_type_arg(regular_only),
        league_id_nullable="00",
    )
    return lg.league_game_finder_results.get_data_frame()


def _resolve_home_away_team_ids(game_rows: pd.DataFrame) -> tuple[int, int]:
    """Infer NBA home and away team IDs from the two LeagueGameFinder rows for one GAME_ID."""
    if len(game_rows) != 2:
        raise ValueError(f"expected 2 rows per game, got {len(game_rows)}")
    m0 = str(game_rows.iloc[0]["MATCHUP"])
    ab0 = str(game_rows.iloc[0]["TEAM_ABBREVIATION"])
    tid0 = int(game_rows.iloc[0]["TEAM_ID"])
    ab1 = str(game_rows.iloc[1]["TEAM_ABBREVIATION"])
    tid1 = int(game_rows.iloc[1]["TEAM_ID"])
    if " @ " in m0:
        away_abbr, home_abbr = [x.strip() for x in m0.split(" @ ", 1)]
        away_id = tid0 if ab0 == away_abbr else tid1
        home_id = tid1 if ab0 == away_abbr else tid0
        return home_id, away_id
    if " vs. " in m0:
        home_abbr, away_abbr = [x.strip() for x in m0.split(" vs. ", 1)]
        home_id = tid0 if ab0 == home_abbr else tid1
        away_id = tid1 if ab0 == home_abbr else tid0
        return home_id, away_id
    raise ValueError(f"unrecognized MATCHUP format: {m0!r}")


def sync_games_from_finder(
    session: Session,
    season: str,
    regular_only: bool,
    teams_by_nba: dict[int, Team],
    max_games: int | None,
) -> tuple[dict[str, Game], list[str]]:
    """Insert/update Game rows from LeagueGameFinder (deduped by NBA GAME_ID).

    Returns mapping nba_game_id -> Game and a stable-ordered list of ids for stats ingestion.
    """
    df = load_season_game_rows(season, regular_only)
    df["GAME_ID"] = df["GAME_ID"].astype(str)
    game_ids = sorted(df["GAME_ID"].unique().tolist())
    if max_games is not None:
        game_ids = game_ids[:max_games]

    games_by_nba_id: dict[str, Game] = {}
    for gid in game_ids:
        gdf = df[df["GAME_ID"] == gid]
        try:
            home_nba, away_nba = _resolve_home_away_team_ids(gdf)
        except Exception as exc:
            logger.warning("Skip game %s: %s", gid, exc)
            continue
        home = teams_by_nba.get(home_nba)
        away = teams_by_nba.get(away_nba)
        if home is None or away is None:
            logger.warning("Skip game %s: unknown team id(s) %s %s", gid, home_nba, away_nba)
            continue
        gd_raw = gdf.iloc[0]["GAME_DATE"]
        if isinstance(gd_raw, str):
            game_date = datetime.strptime(gd_raw, "%Y-%m-%d").date()
        else:
            game_date = pd.Timestamp(gd_raw).date()

        existing = session.scalar(select(Game).where(Game.nba_game_id == gid))
        if existing is None:
            existing = Game(
                nba_game_id=gid,
                home_team_id=home.id,
                away_team_id=away.id,
                game_date=game_date,
                status="scheduled",
            )
            session.add(existing)
        else:
            existing.home_team_id = home.id
            existing.away_team_id = away.id
            existing.game_date = game_date
        games_by_nba_id[gid] = existing

    session.flush()
    logger.info("Synced %d games from LeagueGameFinder", len(games_by_nba_id))
    order = sorted(games_by_nba_id.keys())
    return games_by_nba_id, order


def _summary_status(game_id: str) -> str | None:
    try:
        _pause()
        s = boxscoresummaryv3.BoxScoreSummaryV3(game_id=game_id)
        dfs = s.get_data_frames()
        if not dfs:
            return None
        row = dfs[0].iloc[0]
        return str(row.get("gameStatusText") or row.get("GAME_STATUS_TEXT") or "")
    except Exception:
        return None


def _box_score_rows_v3(game_id: str) -> pd.DataFrame | None:
    _pause()
    try:
        b = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id)
        df = b.player_stats.get_data_frame()
        if df is None or df.empty:
            return None
        return df
    except Exception as exc:
        logger.debug("BoxScoreTraditionalV3 failed for %s: %s", game_id, exc)
        return None


def _box_score_rows_v2(game_id: str) -> pd.DataFrame | None:
    _pause()
    try:
        b = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id)
        df = b.player_stats.get_data_frame()
        if df is None or df.empty:
            return None
        return df
    except Exception as exc:
        logger.debug("BoxScoreTraditionalV2 failed for %s: %s", game_id, exc)
        return None


def _apply_player_stat_row(
    session: Session,
    game: Game,
    nba_player_id: int,
    pts: int,
    reb: int,
    ast: int,
    mins: float,
) -> None:
    player = session.scalar(select(Player).where(Player.nba_player_id == nba_player_id))
    if player is None:
        logger.warning(
            "Skipping stats for unknown NBA player_id=%s in game %s",
            nba_player_id,
            game.nba_game_id,
        )
        return
    row = session.scalar(
        select(PlayerGameStat).where(
            PlayerGameStat.player_id == player.id,
            PlayerGameStat.game_id == game.id,
        )
    )
    if row is None:
        row = PlayerGameStat(
            player_id=player.id,
            game_id=game.id,
            points=pts,
            rebounds=reb,
            assists=ast,
            minutes=mins,
        )
        session.add(row)
    else:
        row.points = pts
        row.rebounds = reb
        row.assists = ast
        row.minutes = mins


def ingest_box_score_for_game(session: Session, game: Game) -> int:
    """Fetch box score and upsert PlayerGameStat rows. Returns rows written/updated."""
    gid = game.nba_game_id
    status = _summary_status(gid)
    if status:
        game.status = status[:64]

    df = _box_score_rows_v3(gid)
    if df is None:
        df = _box_score_rows_v2(gid)
    if df is None:
        logger.warning("No box score for game %s", gid)
        return 0

    n = 0
    if "personId" in df.columns:
        for _, r in df.iterrows():
            pid = int(r["personId"])
            if pid <= 0:
                continue
            pts = normalize_stat_int(r.get("points"))
            reb = normalize_stat_int(r.get("reboundsTotal"))
            ast = normalize_stat_int(r.get("assists"))
            mins = parse_minutes(r.get("minutes"))
            _apply_player_stat_row(session, game, pid, pts, reb, ast, mins)
            n += 1
    else:
        for _, r in df.iterrows():
            pid = int(r["PLAYER_ID"])
            if pid <= 0:
                continue
            pts = normalize_stat_int(r.get("PTS"))
            reb = normalize_stat_int(r.get("REB"))
            ast = normalize_stat_int(r.get("AST"))
            mins = parse_minutes(r.get("MIN"))
            _apply_player_stat_row(session, game, pid, pts, reb, ast, mins)
            n += 1

    session.flush()
    return n


def run_full_ingest(
    session: Session,
    *,
    season: str,
    regular_only: bool,
    max_games: int | None,
    skip_rosters: bool,
    skip_games: bool,
    skip_stats: bool,
) -> None:
    teams_by_nba = sync_teams(session)
    session.commit()

    if not skip_rosters:
        sync_rosters(session, season, teams_by_nba)
        session.commit()

    if skip_games:
        return

    games_map, game_order = sync_games_from_finder(
        session, season, regular_only, teams_by_nba, max_games
    )
    session.commit()

    if skip_stats:
        return

    total_stats = 0
    for gid in game_order:
        game = games_map[gid]
        try:
            total_stats += ingest_box_score_for_game(session, game)
            session.commit()
        except Exception:
            logger.exception("Failed ingesting box score for game %s", game.nba_game_id)
            session.rollback()

    logger.info("Player-game stat rows touched (approx): %d", total_stats)
