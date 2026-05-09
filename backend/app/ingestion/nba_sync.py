"""Sync NBA stats into warehouse tables: teams, players, games, player_game_stats.

Parlay tables (`parlays`, `parlay_legs`) are never written here—they are populated by
the application when users build parlays.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from nba_api.stats.endpoints import (
    boxscoresummaryv3,
    boxscoretraditionalv2,
    boxscoretraditionalv3,
    commonteamroster,
    leaguegamefinder,
    scoreboardv3,
)
from nba_api.live.nba.endpoints.boxscore import BoxScore
from nba_api.stats.library.http import NBAStatsHTTP
from nba_api.stats.static import teams as static_teams
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Game, Player, PlayerGameStat, Team
from app.ingestion.minutes import normalize_stat_int, parse_minutes

logger = logging.getLogger(__name__)

REQUEST_PAUSE_SEC = 0.65
NBA_CALENDAR_TZ = ZoneInfo("America/New_York")


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


def _parse_game_date(gd_raw: object) -> date:
    if isinstance(gd_raw, str):
        return datetime.strptime(gd_raw, "%Y-%m-%d").date()
    return pd.Timestamp(gd_raw).date()


def _parse_game_time_utc(raw: object) -> datetime | None:
    """Parse ScoreboardV3 ``gameTimeUTC`` into timezone-aware UTC."""
    if raw is None:
        return None
    try:
        if isinstance(raw, pd.Timestamp):
            if pd.isna(raw):
                return None
            dt = raw.to_pydatetime()
        elif isinstance(raw, datetime):
            dt = raw
        else:
            s = str(raw).strip()
            if not s:
                return None
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_score(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return None
            return int(float(s))
        if pd.isna(raw):
            return None
        return int(raw)
    except Exception:
        return None


def normalize_nba_game_id_str(raw: object) -> str:
    """Normalize NBA Stats ``GameID`` to a 10-digit string (zero-padded)."""
    if raw is None:
        return ""
    if isinstance(raw, float) and math.isnan(raw):
        return ""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            if isinstance(raw, float) and math.isnan(raw):
                return ""
            raw = int(raw)
        except (ValueError, OverflowError):
            pass
    s = str(raw).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if not s:
        return ""
    if not s.isdigit():
        return s
    return s.zfill(10)


def _safe_nba_person_id(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _fetch_cdn_live_boxscore_game_dict(game_id: str) -> dict | None:
    """Fetch ``cdn.nba.com/static/json/liveData/boxscore/...`` (player rows during live playoffs).

    Stats ``boxscoretraditionalv3`` frequently returns empty ``players`` for in-progress games while
    team scores still update via scoreboard; liveData matches what NBA.com uses in-game.
    """
    _pause()
    try:
        bs = BoxScore(game_id=game_id, timeout=60)
        return (bs.nba_response.get_dict() or {}).get("game") or {}
    except Exception as exc:
        logger.warning("CDN live boxscore fetch failed for %s: %s", game_id, exc)
        return None


def _apply_scores_from_cdn_live_game(game: Game, game_payload: dict) -> None:
    away = game_payload.get("awayTeam") or {}
    home = game_payload.get("homeTeam") or {}
    try:
        if away.get("score") is not None:
            game.away_score = int(away["score"])
        if home.get("score") is not None:
            game.home_score = int(home["score"])
    except (TypeError, ValueError):
        pass


def _apply_players_from_cdn_live_game(session: Session, game: Game, game_payload: dict) -> tuple[int, int]:
    """Upsert stats from CDN liveData boxscore. Returns ``(slots_in_payload, db_rows_written)``."""
    slots = 0
    applied = 0
    for side in ("homeTeam", "awayTeam"):
        team = game_payload.get(side) or {}
        for player in team.get("players") or []:
            pid = _safe_nba_person_id(player.get("personId"))
            if pid is None:
                continue
            stats = player.get("statistics") or {}
            slots += 1
            pts = normalize_stat_int(stats.get("points"))
            reb = normalize_stat_int(stats.get("reboundsTotal"))
            ast = normalize_stat_int(stats.get("assists"))
            mins = parse_minutes(stats.get("minutes"))
            applied += _apply_player_stat_row(session, game, pid, pts, reb, ast, mins)
    return slots, applied


def _fetch_boxscore_traditional_v3_raw_dict(game_id: str) -> dict | None:
    """Fetch ``boxscoretraditionalv3`` JSON without nba_api's parser (avoids crashes when team ``statistics`` is null)."""
    _pause()
    try:
        http = NBAStatsHTTP()
        resp = http.send_api_request(
            endpoint="boxscoretraditionalv3",
            parameters={
                "GameID": game_id,
                "EndPeriod": "0",
                "EndRange": "0",
                "RangeType": "0",
                "StartPeriod": "0",
                "StartRange": "0",
            },
            timeout=60,
        )
        return resp.get_dict()
    except Exception as exc:
        logger.warning("Raw boxscoretraditionalv3 HTTP failed for %s: %s", game_id, exc)
        return None


def _team_points_from_traditional_bt(bt: dict) -> dict[int, int] | None:
    """Team totals from ``boxScoreTraditional``; falls back to summing player points when team statistics are null."""
    out: dict[int, int] = {}
    for side in ("homeTeam", "awayTeam"):
        team = bt.get(side) or {}
        tid = team.get("teamId")
        if tid is None:
            continue
        stats = team.get("statistics") or {}
        pts = stats.get("points")
        if pts is not None:
            try:
                out[int(tid)] = normalize_stat_int(pts)
            except Exception:
                pass
    if len(out) >= 2:
        return out

    sums: dict[int, int] = {}
    for side in ("homeTeam", "awayTeam"):
        team = bt.get(side) or {}
        tid = team.get("teamId")
        if tid is None:
            continue
        total = 0
        for player in team.get("players") or []:
            st = player.get("statistics") or {}
            total += normalize_stat_int(st.get("points"))
        if total > 0:
            sums[int(tid)] = total
    return sums if len(sums) >= 2 else None


def _count_traditional_player_rows(bt: dict) -> int:
    return sum(
        len((bt.get(side) or {}).get("players") or [])
        for side in ("homeTeam", "awayTeam")
    )


def _apply_players_from_traditional_bt(session: Session, game: Game, bt: dict) -> tuple[int, int]:
    """Upsert player stats from ``boxScoreTraditional`` JSON.

    Returns ``(slots_seen_in_api, rows_written_or_updated_in_db)``.
    """
    slots = 0
    applied = 0
    for side in ("homeTeam", "awayTeam"):
        team = bt.get(side) or {}
        for player in team.get("players") or []:
            pid = _safe_nba_person_id(player.get("personId"))
            if pid is None:
                continue
            slots += 1
            stats = player.get("statistics") or {}
            pts = normalize_stat_int(stats.get("points"))
            reb = normalize_stat_int(stats.get("reboundsTotal"))
            ast = normalize_stat_int(stats.get("assists"))
            mins = parse_minutes(stats.get("minutes"))
            applied += _apply_player_stat_row(session, game, pid, pts, reb, ast, mins)
    return slots, applied


def _apply_players_from_traditional_dataframes(session: Session, game: Game, gid: str) -> tuple[int, int]:
    """Fallback: nba_api pandas frames (legacy / odd responses).

    Returns ``(slots_seen_in_api, rows_written_or_updated_in_db)``.
    """
    df = _box_score_rows_v3(gid)
    if df is None:
        df = _box_score_rows_v2(gid)
    if df is None or df.empty:
        return 0, 0
    slots = 0
    applied = 0
    if "personId" in df.columns:
        for _, r in df.iterrows():
            pid = _safe_nba_person_id(r.get("personId"))
            if pid is None:
                continue
            slots += 1
            pts = normalize_stat_int(r.get("points"))
            reb = normalize_stat_int(r.get("reboundsTotal"))
            ast = normalize_stat_int(r.get("assists"))
            mins = parse_minutes(r.get("minutes"))
            applied += _apply_player_stat_row(session, game, pid, pts, reb, ast, mins)
    else:
        for _, r in df.iterrows():
            pid = _safe_nba_person_id(r.get("PLAYER_ID"))
            if pid is None:
                continue
            slots += 1
            pts = normalize_stat_int(r.get("PTS"))
            reb = normalize_stat_int(r.get("REB"))
            ast = normalize_stat_int(r.get("AST"))
            mins = parse_minutes(r.get("MIN"))
            applied += _apply_player_stat_row(session, game, pid, pts, reb, ast, mins)
    return slots, applied


def sync_games_from_finder(
    session: Session,
    season: str,
    regular_only: bool,
    teams_by_nba: dict[int, Team],
    max_games: int | None,
    *,
    recent_first: bool = False,
) -> tuple[dict[str, Game], list[str]]:
    """Insert/update Game rows from LeagueGameFinder (deduped by NBA GAME_ID).

    When ``max_games`` is set, by default the first N game IDs (sorted lexically) are
    used — often early-season games. With ``recent_first=True``, the N games with
    the latest ``GAME_DATE`` are used instead (better for dev datasets).

    Returns mapping nba_game_id -> Game and an ordered list of ids for stats ingestion
    (same order as the filtered ``game_ids`` list, minus any skipped games).
    """
    df = load_season_game_rows(season, regular_only)
    df["GAME_ID"] = df["GAME_ID"].map(normalize_nba_game_id_str)
    all_ids = sorted(df["GAME_ID"].unique().tolist())
    if max_games is not None:
        if recent_first:
            dated: list[tuple[str, date]] = []
            for gid in all_ids:
                gdf = df[df["GAME_ID"] == gid]
                gd_raw = gdf.iloc[0]["GAME_DATE"]
                dated.append((gid, _parse_game_date(gd_raw)))
            dated.sort(key=lambda t: (t[1], t[0]), reverse=True)
            game_ids = [d[0] for d in dated[:max_games]]
        else:
            game_ids = all_ids[:max_games]
    else:
        game_ids = all_ids

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
        game_date = _parse_game_date(gd_raw)

        existing = session.scalar(select(Game).where(Game.nba_game_id == gid))
        if existing is None:
            existing = Game(
                nba_game_id=gid,
                home_team_id=home.id,
                away_team_id=away.id,
                game_date=game_date,
                home_score=None,
                away_score=None,
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
    order = [gid for gid in game_ids if gid in games_by_nba_id]
    return games_by_nba_id, order


def sync_games_from_scoreboard(session: Session, teams_by_nba: dict[int, Team], *, days: int) -> list[Game]:
    """Upsert games from Stats ``ScoreboardV3`` for ``days`` consecutive NBA Eastern calendar days starting today.

    Covers same-day and upcoming games that ``LeagueGameFinder`` may omit or lag on.
    Team line rows list **home first**, **away second** (validated against ``gameCode``).
    """
    if days < 1:
        raise ValueError("days must be >= 1")

    today = datetime.now(NBA_CALENDAR_TZ).date()
    touched: list[Game] = []

    for offset in range(days):
        slate = today + timedelta(days=offset)
        date_str = slate.isoformat()
        _pause()
        try:
            sb = scoreboardv3.ScoreboardV3(game_date=date_str)
            dfs = sb.get_data_frames()
        except Exception as exc:
            logger.warning("Scoreboard fetch failed for %s: %s", date_str, exc)
            continue

        if len(dfs) < 3 or dfs[1] is None or dfs[1].empty:
            logger.debug("Scoreboard: no games header rows on %s", date_str)
            continue

        games_hdr = dfs[1]
        teams_lines = dfs[2]
        if teams_lines is None or teams_lines.empty:
            logger.warning("Scoreboard: missing team lines on %s", date_str)
            continue

        games_hdr = games_hdr.copy()
        games_hdr["gameId"] = games_hdr["gameId"].map(normalize_nba_game_id_str)
        teams_lines = teams_lines.copy()
        teams_lines["gameId"] = teams_lines["gameId"].map(normalize_nba_game_id_str)

        for _, hdr in games_hdr.iterrows():
            nba_gid = str(hdr["gameId"]).strip()
            status_txt = str(hdr.get("gameStatusText") or "").strip()[:64] or "scheduled"
            tip_utc = _parse_game_time_utc(hdr.get("gameTimeUTC"))

            sub = teams_lines[teams_lines["gameId"] == nba_gid]
            if len(sub) != 2:
                logger.warning(
                    "Scoreboard: skip game %s on %s: expected 2 team rows, got %d",
                    nba_gid,
                    date_str,
                    len(sub),
                )
                continue

            home_nba_id = int(sub.iloc[0]["teamId"])
            away_nba_id = int(sub.iloc[1]["teamId"])
            home_score = _parse_score(sub.iloc[0].get("score"))
            away_score = _parse_score(sub.iloc[1].get("score"))

            home = teams_by_nba.get(home_nba_id)
            away = teams_by_nba.get(away_nba_id)
            if home is None or away is None:
                logger.warning(
                    "Scoreboard: skip game %s on %s: unknown team home=%s away=%s",
                    nba_gid,
                    date_str,
                    home_nba_id,
                    away_nba_id,
                )
                continue

            existing = session.scalar(select(Game).where(Game.nba_game_id == nba_gid))
            if existing is None:
                existing = Game(
                    nba_game_id=nba_gid,
                    home_team_id=home.id,
                    away_team_id=away.id,
                    game_date=slate,
                    game_time_utc=tip_utc,
                    home_score=home_score,
                    away_score=away_score,
                    status=status_txt,
                )
                session.add(existing)
            else:
                existing.home_team_id = home.id
                existing.away_team_id = away.id
                existing.status = status_txt[:64]
                if tip_utc is not None:
                    existing.game_time_utc = tip_utc
                existing.home_score = home_score
                existing.away_score = away_score

            touched.append(existing)

    session.flush()
    logger.info(
        "Scoreboard sync processed %d game row touch(es) over %d Eastern day(s)",
        len(touched),
        days,
    )
    return touched


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


def _box_score_team_points_v3(game_id: str) -> dict[int, int] | None:
    _pause()
    try:
        b = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id)
        df = b.team_stats.get_data_frame()
        if df is None or df.empty:
            return None
        out: dict[int, int] = {}
        for _, r in df.iterrows():
            tid = int(r.get("teamId"))
            pts = normalize_stat_int(r.get("points"))
            if tid > 0:
                out[tid] = pts
        return out if out else None
    except Exception as exc:
        logger.debug("BoxScoreTraditionalV3 team_stats failed for %s: %s", game_id, exc)
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


def _box_score_team_points_v2(game_id: str) -> dict[int, int] | None:
    _pause()
    try:
        b = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id)
        df = b.team_stats.get_data_frame()
        if df is None or df.empty:
            return None
        out: dict[int, int] = {}
        for _, r in df.iterrows():
            tid = int(r.get("TEAM_ID"))
            pts = normalize_stat_int(r.get("PTS"))
            if tid > 0:
                out[tid] = pts
        return out if out else None
    except Exception as exc:
        logger.debug("BoxScoreTraditionalV2 team_stats failed for %s: %s", game_id, exc)
        return None


def _apply_player_stat_row(
    session: Session,
    game: Game,
    nba_player_id: int,
    pts: int,
    reb: int,
    ast: int,
    mins: float,
) -> int:
    """Upsert one ``PlayerGameStat``. Returns ``1`` if written, ``0`` if player unknown."""
    player = session.scalar(select(Player).where(Player.nba_player_id == nba_player_id))
    if player is None:
        logger.warning(
            "Skipping stats for unknown NBA player_id=%s in game %s",
            nba_player_id,
            game.nba_game_id,
        )
        return 0
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
    return 1


def ingest_box_score_for_game(session: Session, game: Game) -> int:
    """Fetch box score and upsert PlayerGameStat rows. Returns **DB rows written/updated**."""
    gid = normalize_nba_game_id_str(game.nba_game_id)
    if len(gid) != 10 or not gid.isdigit():
        logger.warning("Bad NBA game id for box score: db_game.id=%s nba_game_id=%r", game.id, game.nba_game_id)
        return 0

    status = _summary_status(gid)
    if status:
        game.status = status[:64]

    # One Stats JSON fetch that matches what the league site uses; prefer it over nba_api DataFrames
    # (V2 is empty for 2025-26+, and the V3 pandas parser can throw when team ``statistics`` is null).
    traditional_raw = _fetch_boxscore_traditional_v3_raw_dict(gid)
    bt = (traditional_raw or {}).get("boxScoreTraditional") or {}
    api_slots = _count_traditional_player_rows(bt)

    pts_by_team = _team_points_from_traditional_bt(bt)
    if not pts_by_team:
        pts_by_team = _box_score_team_points_v3(gid)
    if pts_by_team is None:
        pts_by_team = _box_score_team_points_v2(gid)
    if pts_by_team:
        # team_stats returns NBA team IDs, while Game stores local Team PKs.
        home_team = session.get(Team, game.home_team_id)
        away_team = session.get(Team, game.away_team_id)
        if home_team is not None:
            game.home_score = pts_by_team.get(home_team.nba_team_id)
        if away_team is not None:
            game.away_score = pts_by_team.get(away_team.nba_team_id)

    applied = 0
    source = "none"
    slots_trad = 0
    slots_live = 0

    if api_slots > 0:
        slots_trad, applied = _apply_players_from_traditional_bt(session, game, bt)
        if applied > 0:
            source = "traditional_json"

    if applied == 0:
        live_payload = _fetch_cdn_live_boxscore_game_dict(gid)
        if live_payload:
            gst = live_payload.get("gameStatusText")
            if gst:
                game.status = str(gst).strip()[:64]
            _apply_scores_from_cdn_live_game(game, live_payload)
            slots_live, applied_live = _apply_players_from_cdn_live_game(session, game, live_payload)
            if applied_live > 0:
                applied = applied_live
                source = "cdn_live"

    if applied == 0:
        slots_df, applied_df = _apply_players_from_traditional_dataframes(session, game, gid)
        if applied_df > 0:
            applied = applied_df
            source = "traditional_dataframe"
        slots_seen_warn = max(slots_trad, slots_live, slots_df)
    else:
        slots_seen_warn = max(slots_trad, slots_live)

    away_s = game.away_score
    home_s = game.home_score
    logger.info(
        "Box ingest nba_game_id=%s status=%r trad_slots=%d live_slots=%d applied_db=%d source=%s score=%s-%s",
        gid,
        (game.status or "")[:48],
        slots_trad,
        slots_live,
        applied,
        source,
        away_s,
        home_s,
    )

    if slots_seen_warn > 0 and applied == 0:
        logger.warning(
            "NBA/CDN returned %d player stat slots for nba_game_id=%s but wrote 0 to DB — "
            "sync rosters (run ingest with WORKER_SKIP_ROSTERS=false or CLI without --skip-rosters).",
            slots_seen_warn,
            gid,
        )
    elif applied == 0 and api_slots == 0 and slots_live == 0:
        logger.info(
            "nba_game_id=%s: no player lines from Stats traditional or CDN liveData yet (pregame / API gap).",
            gid,
        )

    session.flush()
    return applied


def run_full_ingest(
    session: Session,
    *,
    season: str,
    regular_only: bool,
    max_games: int | None,
    recent_first: bool,
    scoreboard_days: int | None,
    skip_rosters: bool,
    skip_games: bool,
    skip_stats: bool,
) -> None:
    teams_by_nba = sync_teams(session)
    session.commit()

    if not skip_rosters:
        sync_rosters(session, season, teams_by_nba)
        session.commit()

    games_map: dict[str, Game] = {}
    game_order: list[str] = []

    if not skip_games:
        games_map, game_order = sync_games_from_finder(
            session,
            season,
            regular_only,
            teams_by_nba,
            max_games,
            recent_first=recent_first,
        )
        session.commit()

    scoreboard_games: list[Game] = []
    if scoreboard_days is not None and scoreboard_days > 0:
        scoreboard_games = sync_games_from_scoreboard(session, teams_by_nba, days=scoreboard_days)
        session.commit()

    if skip_stats:
        return

    seen_nba: set[str] = set()
    total_stats = 0

    for gid in game_order:
        game = games_map[gid]
        seen_nba.add(game.nba_game_id)
        try:
            total_stats += ingest_box_score_for_game(session, game)
            session.commit()
        except Exception:
            logger.exception("Failed ingesting box score for game %s", game.nba_game_id)
            session.rollback()

    for game in scoreboard_games:
        if game.nba_game_id in seen_nba:
            continue
        seen_nba.add(game.nba_game_id)
        try:
            total_stats += ingest_box_score_for_game(session, game)
            session.commit()
        except Exception:
            logger.exception("Failed ingesting box score for game %s", game.nba_game_id)
            session.rollback()

    logger.info("Player-game stat rows touched (approx): %d", total_stats)
