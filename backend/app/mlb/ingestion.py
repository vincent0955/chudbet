"""MLB ingestion service (Requirements 3, 4, 5).

Loads MLB teams, rosters, schedule, and box scores into the shared, sport-
discriminated warehouse tables via the keyless :class:`MLBStatsAPIClient`. This
module mirrors the structure of ``app.ingestion.nba_sync`` (upsert by sport-
native id, ``select`` + ``flush``) but writes MLB rows (``sport=Sport.MLB``) and
reaches the Stats API only through the injected client.

This module is part of the dedicated ``app.mlb`` package (Requirement 2.1): all
MLB ingestion logic lives here, never inside ``app.ingestion.nba_sync``. Network
access is confined to :class:`MLBStatsAPIClient` (Requirement 2.2); this module
imports only that client, never ``statsapi`` directly.

Implemented here:

- ``sync_teams``                -- Requirement 3.1
- ``sync_rosters``              -- Requirements 3.2-3.5
- ``sync_schedule``             -- Requirements 4.1-4.6
- ``ingest_box_score_for_game`` -- Requirements 5.1-5.6
- ``run_full_mlb_ingest``       -- Requirement 6.5 (batch-resilient orchestration)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import Sport
from app.db.models import Game, Player, Team
from app.db.models.mlb_player_game_stats import MLBPlayerGameStat
from app.mlb.config import get_schedule_lookback_days, get_schedule_max_days
from app.mlb.enums import MLBStatType
from app.mlb.status import MLBGameStatus, classify_status
from app.mlb.stats_api_client import (
    MLBStatsAPIClient,
    MLBStatsAPIError,
    RosterEntry,
    SchedulePayload,
    TeamPayload,
)

logger = logging.getLogger(__name__)

__all__ = [
    "sync_teams",
    "sync_rosters",
    "sync_schedule",
    "ingest_box_score_for_game",
    "MLBIngestSummary",
    "run_full_mlb_ingest",
]


# --- payload parsing helpers ------------------------------------------------


def _safe_positive_int(raw: Any) -> int | None:
    """Coerce ``raw`` to a positive int, returning ``None`` when not possible."""
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _clean_str(raw: Any) -> str | None:
    """Return a stripped non-empty string, or ``None`` when blank/missing."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _parse_team_payload(payload: TeamPayload) -> tuple[int, str, str | None] | None:
    """Extract ``(mlb_team_id, full_name, abbreviation)`` from a team payload.

    Returns ``None`` when the payload lacks a usable MLB_Team_ID or full name so
    the caller can skip it with a diagnostic rather than persist a broken row.
    """
    if not isinstance(payload, dict):
        return None
    mlb_team_id = _safe_positive_int(payload.get("id"))
    name = _clean_str(payload.get("name"))
    if mlb_team_id is None or name is None:
        return None
    abbreviation = _clean_str(payload.get("abbreviation"))
    return mlb_team_id, name, abbreviation


def _parse_roster_entry(entry: RosterEntry) -> tuple[int, str, str | None] | None:
    """Extract ``(mlb_player_id, full_name, primary_position)`` from a roster entry.

    Returns ``None`` when the entry lacks a usable MLB_Player_ID or full name.
    ``primary_position`` prefers the position abbreviation (e.g. ``"P"``, ``"CF"``)
    used downstream to distinguish pitchers from non-pitchers, falling back to the
    position type/name when no abbreviation is reported.
    """
    if not isinstance(entry, dict):
        return None
    person = entry.get("person") or {}
    mlb_player_id = _safe_positive_int(person.get("id"))
    full_name = _clean_str(person.get("fullName"))
    if mlb_player_id is None or full_name is None:
        return None
    position = entry.get("position") or {}
    primary_position = (
        _clean_str(position.get("abbreviation"))
        or _clean_str(position.get("type"))
        or _clean_str(position.get("name"))
    )
    return mlb_player_id, full_name, primary_position


# --- teams (Req 3.1) --------------------------------------------------------


def sync_teams(session: Session, client: MLBStatsAPIClient) -> dict[int, Team]:
    """Upsert current MLB teams keyed by MLB_Team_ID (Requirement 3.1).

    Each team reported by the client is upserted with its full name and
    abbreviation and associated with the ``MLB`` sport. An existing team for an
    MLB_Team_ID is updated in place rather than duplicated (Req 3.3). Returns a
    ``{mlb_team_id: Team}`` map for roster ingestion.
    """
    payloads = client.teams()
    by_mlb_id: dict[int, Team] = {}
    for payload in payloads:
        parsed = _parse_team_payload(payload)
        if parsed is None:
            logger.warning("Skipping MLB team payload missing id/name: %r", payload)
            continue
        mlb_team_id, name, abbreviation = parsed

        team = session.scalar(select(Team).where(Team.mlb_team_id == mlb_team_id))
        if team is None:
            team = Team(
                sport=Sport.MLB,
                mlb_team_id=mlb_team_id,
                name=name,
                abbreviation=abbreviation,
            )
            session.add(team)
        else:
            team.name = name
            team.abbreviation = abbreviation
            team.sport = Sport.MLB
        by_mlb_id[mlb_team_id] = team

    session.flush()
    logger.info("Synced %d MLB teams", len(by_mlb_id))
    return by_mlb_id


# --- rosters (Req 3.2-3.5) --------------------------------------------------


def sync_rosters(
    session: Session,
    client: MLBStatsAPIClient,
    teams_by_mlb_id: dict[int, Team],
) -> None:
    """Upsert each team's active-roster players keyed by MLB_Player_ID (Req 3.2-3.5).

    For every team, each rostered player is upserted with full name and primary
    position and associated with that team (Req 3.2). An existing player is
    updated rather than duplicated (Req 3.3); a player previously associated with
    a different team has its ``team_id`` reassigned to the team currently being
    ingested (Req 3.4). A team the client reports with no roster entries is
    completed without inserting any player and recorded with a diagnostic log
    naming the team (Req 3.5).
    """
    upserted = 0
    for mlb_team_id, team in teams_by_mlb_id.items():
        entries = client.roster(mlb_team_id)
        if not entries:
            # Req 3.5: empty roster -> no inserts, diagnostic naming the team.
            logger.info(
                "MLB team %s (mlb_team_id=%s) returned no roster entries; "
                "completing with no player inserts",
                team.name,
                mlb_team_id,
            )
            continue

        for entry in entries:
            parsed = _parse_roster_entry(entry)
            if parsed is None:
                logger.warning(
                    "Skipping MLB roster entry missing person id/name on team %s: %r",
                    team.name,
                    entry,
                )
                continue
            mlb_player_id, full_name, primary_position = parsed

            player = session.scalar(
                select(Player).where(Player.mlb_player_id == mlb_player_id)
            )
            if player is None:
                player = Player(
                    sport=Sport.MLB,
                    mlb_player_id=mlb_player_id,
                    full_name=full_name,
                    primary_position=primary_position,
                    team_id=team.id,
                )
                session.add(player)
            else:
                player.full_name = full_name
                player.primary_position = primary_position
                # Req 3.4: reassign association to the team being ingested.
                player.team_id = team.id
                player.sport = Sport.MLB
            upserted += 1

        logger.debug("MLB roster team %s: %d entries", team.name, len(entries))

    session.flush()
    logger.info("Upserted MLB roster rows (total iterations): %d", upserted)


# --- schedule payload parsing helpers ---------------------------------------


def _parse_game_datetime(raw: Any) -> datetime | None:
    """Parse the Stats API ``game_datetime`` (ISO 8601, UTC ``Z``) into UTC.

    Returns ``None`` when the value is missing or unparseable so the caller can
    still store the game keyed by date with a ``NULL`` start time.
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_schedule_date(raw: Any, fallback: datetime | None) -> date | None:
    """Parse the Stats API ``game_date`` (``YYYY-MM-DD``).

    Falls back to the UTC date of ``fallback`` (the parsed start time) when the
    explicit date is missing/unparseable, and returns ``None`` when neither is
    available so the caller can skip a game with no usable date.
    """
    if raw is not None:
        text = str(raw).strip()
        if text:
            try:
                return datetime.strptime(text, "%Y-%m-%d").date()
            except ValueError:
                pass
    if fallback is not None:
        return fallback.date()
    return None


def _parse_run_total(raw: Any) -> int | None:
    """Coerce a reported run total to a non-negative int, else ``None``.

    A missing, blank, non-numeric, or negative value yields ``None`` so the
    caller treats the run total as *not reported* and leaves storage unchanged
    (Req 4.4).
    """
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            value = int(float(text))
        else:
            value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


class _ParsedSchedule:
    """Normalized fields extracted from one Stats API schedule entry."""

    __slots__ = (
        "mlb_game_id",
        "home_mlb_id",
        "away_mlb_id",
        "game_date",
        "start_utc",
        "status_text",
        "home_score",
        "away_score",
    )

    def __init__(
        self,
        mlb_game_id: int,
        home_mlb_id: int,
        away_mlb_id: int,
        game_date: date,
        start_utc: datetime | None,
        status_text: str | None,
        home_score: int | None,
        away_score: int | None,
    ) -> None:
        self.mlb_game_id = mlb_game_id
        self.home_mlb_id = home_mlb_id
        self.away_mlb_id = away_mlb_id
        self.game_date = game_date
        self.start_utc = start_utc
        self.status_text = status_text
        self.home_score = home_score
        self.away_score = away_score


def _parse_schedule_payload(payload: SchedulePayload) -> _ParsedSchedule | None:
    """Extract the fields ``sync_schedule`` needs from one schedule entry.

    Returns ``None`` when the entry lacks a usable MLB_Game_ID, both team ids, or
    a usable game date so the caller can skip it with a diagnostic rather than
    persist a broken row.
    """
    if not isinstance(payload, dict):
        return None
    mlb_game_id = _safe_positive_int(payload.get("game_id"))
    home_mlb_id = _safe_positive_int(payload.get("home_id"))
    away_mlb_id = _safe_positive_int(payload.get("away_id"))
    if mlb_game_id is None or home_mlb_id is None or away_mlb_id is None:
        return None
    start_utc = _parse_game_datetime(payload.get("game_datetime"))
    game_date = _parse_schedule_date(payload.get("game_date"), start_utc)
    if game_date is None:
        return None
    status_text = _clean_str(payload.get("status"))
    return _ParsedSchedule(
        mlb_game_id=mlb_game_id,
        home_mlb_id=home_mlb_id,
        away_mlb_id=away_mlb_id,
        game_date=game_date,
        start_utc=start_utc,
        status_text=status_text,
        home_score=_parse_run_total(payload.get("home_score")),
        away_score=_parse_run_total(payload.get("away_score")),
    )


def _resolve_window_days(window_days: int) -> int:
    """Clamp the requested window to ``[1, MLB_SCHEDULE_MAX_DAYS]`` (Req 4.1)."""
    max_days = get_schedule_max_days()
    if max_days < 1:
        max_days = 1
    return max(1, min(int(window_days), max_days))


def _mlb_team_by_native_id(session: Session, mlb_team_id: int) -> Team | None:
    """Look up an MLB team by its sport-native id, scoped to ``sport=MLB``."""
    return session.scalar(
        select(Team).where(
            Team.mlb_team_id == mlb_team_id, Team.sport == Sport.MLB
        )
    )


def _apply_run_totals(
    game: Game, status: MLBGameStatus, home_score: int | None, away_score: int | None
) -> None:
    """Overwrite stored run totals only when reported, else leave unchanged.

    Run totals are considered *reported* only once a game is LIVE or FINAL and
    both sides carry a usable non-negative integer; a PRE_GAME game (or a payload
    with missing/blank scores) leaves the stored totals untouched (Req 4.4).
    While FINAL, the reported values are the final run totals (Req 4.5).
    """
    if status is MLBGameStatus.PRE_GAME:
        return
    if home_score is None or away_score is None:
        return
    game.home_score = home_score
    game.away_score = away_score


# --- schedule (Req 4.1-4.6) -------------------------------------------------


def sync_schedule(
    session: Session,
    client: MLBStatsAPIClient,
    *,
    window_days: int,
    lookback_days: int | None = None,
) -> dict[int, Game]:
    """Upsert one ``Game`` per scheduled MLB game in the window (Req 4.1-4.6).

    Fetches the schedule from ``today - lookback_days`` through
    ``today + forward_window - 1`` (UTC). The forward span is clamped to
    ``MLB_SCHEDULE_MAX_DAYS``; lookback defaults to ``MLB_SCHEDULE_LOOKBACK_DAYS``
    so recent finals are available for game-market and prop pricing samples.
    home/away team, game date, and UTC start time (Req 4.1). Each game's status
    text is classified into exactly one of PRE_GAME / LIVE / FINAL (Req 4.2). An
    existing game has its status and scheduled start updated rather than being
    duplicated (Req 4.3). Reported run totals overwrite the stored totals and are
    otherwise left unchanged (Req 4.4); while FINAL the reported values are stored
    as the final totals (Req 4.5). A game referencing a team absent from the
    database is skipped, leaving any existing row for that MLB_Game_ID unchanged,
    with a diagnostic naming the game and the missing team (Req 4.6).

    Returns a ``{mlb_game_id: Game}`` map of the games upserted this run.
    """
    days = _resolve_window_days(window_days)
    if lookback_days is None:
        lookback_days = get_schedule_lookback_days()
    lookback_days = max(0, int(lookback_days))

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days)
    end = today + timedelta(days=days - 1)

    payloads = client.schedule(start, end)
    games_by_mlb_id: dict[int, Game] = {}

    for payload in payloads:
        parsed = _parse_schedule_payload(payload)
        if parsed is None:
            logger.warning(
                "Skipping MLB schedule entry missing id/teams/date: %r", payload
            )
            continue

        home = _mlb_team_by_native_id(session, parsed.home_mlb_id)
        away = _mlb_team_by_native_id(session, parsed.away_mlb_id)
        if home is None or away is None:
            # Req 4.6: unknown team -> skip, leave any existing row unchanged,
            # diagnostic naming the game and the missing team(s).
            missing = []
            if home is None:
                missing.append(f"home mlb_team_id={parsed.home_mlb_id}")
            if away is None:
                missing.append(f"away mlb_team_id={parsed.away_mlb_id}")
            logger.warning(
                "Skipping MLB game mlb_game_id=%s: unknown team(s): %s",
                parsed.mlb_game_id,
                ", ".join(missing),
            )
            continue

        status = classify_status(None, parsed.status_text)
        # Persist the raw status text for display, falling back to the
        # classified value when the API reports no status text.
        status_value = (parsed.status_text or status.value)[:64]
        native_id = str(parsed.mlb_game_id)

        game = session.scalar(select(Game).where(Game.mlb_game_id == native_id))
        if game is None:
            game = Game(
                sport=Sport.MLB,
                mlb_game_id=native_id,
                home_team_id=home.id,
                away_team_id=away.id,
                game_date=parsed.game_date,
                game_time_utc=parsed.start_utc,
                status=status_value,
                home_score=None,
                away_score=None,
            )
            session.add(game)
        else:
            # Req 4.3: update status and scheduled start on the existing game.
            game.home_team_id = home.id
            game.away_team_id = away.id
            game.game_date = parsed.game_date
            if parsed.start_utc is not None:
                game.game_time_utc = parsed.start_utc
            game.status = status_value
            game.sport = Sport.MLB

        _apply_run_totals(game, status, parsed.home_score, parsed.away_score)
        games_by_mlb_id[parsed.mlb_game_id] = game

    session.flush()
    logger.info(
        "Synced %d MLB games for window %s..%s (lookback=%d day(s), forward=%d day(s))",
        len(games_by_mlb_id),
        start.isoformat(),
        end.isoformat(),
        lookback_days,
        days,
    )
    return games_by_mlb_id


def _games_for_box_score_batch(
    session: Session,
    synced: dict[int, Game],
    *,
    lookback_days: int,
) -> list[Game]:
    """Return non-PRE_GAME MLB games in the lookback window for box-score refresh."""
    by_id: dict[int, Game] = {game.id: game for game in synced.values()}
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(0, int(lookback_days)))

    extra = session.scalars(
        select(Game).where(
            Game.sport == Sport.MLB,
            Game.game_date >= cutoff,
            Game.mlb_game_id.is_not(None),
        )
    ).all()
    for game in extra:
        by_id.setdefault(game.id, game)

    return [
        game
        for game in by_id.values()
        if classify_status(None, game.status) is not MLBGameStatus.PRE_GAME
        and _game_needs_box_score(session, game)
    ]


# --- box-score payload parsing helpers --------------------------------------


# Maps each MLB_Stat_Type to the column it populates on ``MLBPlayerGameStat``.
_STAT_COLUMNS: dict[MLBStatType, str] = {
    MLBStatType.HITS: "hits",
    MLBStatType.TOTAL_BASES: "total_bases",
    MLBStatType.RBI: "rbi",
    MLBStatType.RUNS: "runs",
    MLBStatType.STRIKEOUTS_PITCHER: "strikeouts_pitcher",
}


def _box_stat_value(raw: Any) -> int:
    """Coerce one reported box-score stat to a non-negative int.

    A missing, blank, non-numeric, or negative value is treated as *not reported*
    and yields ``0`` (Req 5.1: unreported stats are set to 0). A reported value is
    returned as its non-negative integer.
    """
    if raw is None:
        return 0
    try:
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return 0
            value = int(float(text))
        else:
            value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


class _ParsedBoxLine:
    """A single player's reported MLB_Stat_Type values from a box score."""

    __slots__ = ("mlb_player_id", "values")

    def __init__(self, mlb_player_id: int, values: dict[MLBStatType, int]) -> None:
        self.mlb_player_id = mlb_player_id
        self.values = values


def _parse_box_player(entry: Any) -> _ParsedBoxLine | None:
    """Extract one player's MLB_Player_ID and per-stat values from a box entry.

    Returns ``None`` when the entry is malformed or lacks a usable MLB_Player_ID
    so the caller skips it without persisting a broken row. Every MLB_Stat_Type
    is populated -- batting stats from ``stats.batting`` and the pitcher strikeout
    from ``stats.pitching`` -- with unreported stats defaulting to ``0`` (Req 5.1).
    """
    if not isinstance(entry, dict):
        return None
    person = entry.get("person") or {}
    mlb_player_id = _safe_positive_int(person.get("id"))
    if mlb_player_id is None:
        return None
    stats = entry.get("stats") or {}
    batting = stats.get("batting") if isinstance(stats, dict) else None
    pitching = stats.get("pitching") if isinstance(stats, dict) else None
    batting = batting if isinstance(batting, dict) else {}
    pitching = pitching if isinstance(pitching, dict) else {}
    values = {
        MLBStatType.HITS: _box_stat_value(batting.get("hits")),
        MLBStatType.TOTAL_BASES: _box_stat_value(batting.get("totalBases")),
        MLBStatType.RBI: _box_stat_value(batting.get("rbi")),
        MLBStatType.RUNS: _box_stat_value(batting.get("runs")),
        MLBStatType.STRIKEOUTS_PITCHER: _box_stat_value(pitching.get("strikeOuts")),
    }
    return _ParsedBoxLine(mlb_player_id, values)


def _iter_box_lines(payload: Any) -> list[_ParsedBoxLine]:
    """Collect every parseable player box line from both sides of a box score.

    Iterates the ``home`` and ``away`` ``players`` maps reported by
    ``statsapi.boxscore_data``. Entries that are malformed or lack a usable
    MLB_Player_ID are dropped. Returns an empty list when the payload carries no
    usable player data, which the caller treats as "no usable box-score data"
    (Req 5.6).
    """
    lines: list[_ParsedBoxLine] = []
    if not isinstance(payload, dict):
        return lines
    for side_key in ("home", "away"):
        side = payload.get(side_key)
        if not isinstance(side, dict):
            continue
        players = side.get("players")
        if not isinstance(players, dict):
            continue
        for entry in players.values():
            parsed = _parse_box_player(entry)
            if parsed is not None:
                lines.append(parsed)
    return lines


def _team_runs_from_boxscore(payload: Any) -> tuple[int | None, int | None]:
    """Read home/away run totals from ``statsapi.boxscore_data`` batting totals."""
    if not isinstance(payload, dict):
        return None, None
    home = payload.get("homeBattingTotals")
    away = payload.get("awayBattingTotals")
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None, None
    if home.get("r") is None or away.get("r") is None:
        return None, None
    return _parse_run_total(home.get("r")), _parse_run_total(away.get("r"))


def _apply_team_runs_from_boxscore(
    game: Game, payload: Any, status: MLBGameStatus
) -> None:
    """Persist final/live run totals from a box score when the schedule lacks them."""
    if status is MLBGameStatus.PRE_GAME:
        return
    home_r, away_r = _team_runs_from_boxscore(payload)
    if home_r is None or away_r is None:
        return
    game.home_score = home_r
    game.away_score = away_r


def _game_needs_box_score(session: Session, game: Game) -> bool:
    """Return whether a game still needs a box-score fetch this ingest run."""
    status = classify_status(None, game.status)
    if status is MLBGameStatus.PRE_GAME:
        return False
    if game.home_score is None or game.away_score is None:
        return True
    if status is MLBGameStatus.LIVE:
        return True
    existing = session.scalar(
        select(func.count())
        .select_from(MLBPlayerGameStat)
        .where(MLBPlayerGameStat.game_id == game.id)
    )
    return not existing


def _apply_box_line(
    record: MLBPlayerGameStat, values: dict[MLBStatType, int], status: MLBGameStatus
) -> None:
    """Write a player's reported stats onto an existing stat record by status.

    While FINAL, each MLB_Stat_Type is overwritten with the final reported value
    regardless of magnitude (Req 5.3); while LIVE, each value is set to the
    greater of the stored and newly reported value to avoid mid-game regressions
    (Req 5.2). PRE_GAME never reaches here (box-score ingestion is short-circuited
    upstream, Req 5.4).
    """
    for stat, column in _STAT_COLUMNS.items():
        new_value = values[stat]
        if status is MLBGameStatus.FINAL:
            setattr(record, column, new_value)
        else:  # LIVE
            setattr(record, column, max(getattr(record, column), new_value))


# --- box scores (Req 5.1-5.6) -----------------------------------------------


def ingest_box_score_for_game(
    session: Session,
    client: MLBStatsAPIClient,
    game: Game,
) -> int:
    """Upsert MLB box-score player stats for one game (Req 5.1-5.6).

    Classifies the game's stored status and, while the game is PRE_GAME, creates
    or modifies nothing (Req 5.4). Otherwise fetches the box score through the
    client and upserts exactly one :class:`MLBPlayerGameStat` per player that has
    a box-score entry, keyed by ``(player_id, game_id)``: each MLB_Stat_Type is
    populated with the player's reported non-negative integer and any unreported
    stat is set to ``0`` (Req 5.1). While LIVE, an existing record's values are
    raised to ``max(stored, reported)`` (Req 5.2); while FINAL they are
    overwritten with the final reported values (Req 5.3). A box line for a player
    absent from the database is skipped with a diagnostic naming the MLB_Player_ID
    and MLB_Game_ID, leaving all other players' stats for the game intact
    (Req 5.5). When no usable box-score data is available, existing records are
    left unchanged and a diagnostic naming the game is recorded (Req 5.6).

    Returns the number of stat records inserted or updated this run. May raise
    :class:`MLBStatsAPIError` from the client, which the batch orchestration
    catches per game so one failure does not abort the batch (Req 6.5).
    """
    status = classify_status(None, game.status)

    # Req 5.4: while PRE_GAME, create/modify nothing (and issue no request).
    if status is MLBGameStatus.PRE_GAME:
        logger.debug(
            "Skipping box-score ingestion for PRE_GAME game mlb_game_id=%s",
            game.mlb_game_id,
        )
        return 0

    mlb_game_id = _safe_positive_int(game.mlb_game_id)
    if mlb_game_id is None:
        # Not an addressable MLB game id -> nothing usable to fetch (Req 5.6).
        logger.warning(
            "Skipping box-score ingestion: game id=%s has no usable MLB_Game_ID (%r)",
            game.id,
            game.mlb_game_id,
        )
        return 0

    payload = client.boxscore(mlb_game_id)
    _apply_team_runs_from_boxscore(game, payload, status)
    lines = _iter_box_lines(payload)
    if not lines:
        # Req 5.6: no usable box-score data -> leave existing stats unchanged,
        # diagnostic naming the game.
        logger.warning(
            "No usable box-score data for MLB game mlb_game_id=%s; "
            "leaving existing player stats unchanged",
            mlb_game_id,
        )
        return 0

    upserted = 0
    for line in lines:
        player = session.scalar(
            select(Player).where(
                Player.mlb_player_id == line.mlb_player_id,
                Player.sport == Sport.MLB,
            )
        )
        if player is None:
            # Req 5.5: stat line for a player absent from the DB is skipped with a
            # diagnostic; other players' stats for the game are untouched.
            logger.warning(
                "Skipping box-score stats for unknown player mlb_player_id=%s "
                "in MLB game mlb_game_id=%s",
                line.mlb_player_id,
                mlb_game_id,
            )
            continue

        record = session.scalar(
            select(MLBPlayerGameStat).where(
                MLBPlayerGameStat.player_id == player.id,
                MLBPlayerGameStat.game_id == game.id,
            )
        )
        if record is None:
            # New record: each stat is set to its reported value (or 0); for LIVE
            # and FINAL alike a fresh insert carries the reported values (Req 5.1).
            record = MLBPlayerGameStat(
                player_id=player.id,
                game_id=game.id,
                **{column: line.values[stat] for stat, column in _STAT_COLUMNS.items()},
            )
            session.add(record)
        else:
            _apply_box_line(record, line.values, status)
        upserted += 1

    session.flush()
    logger.info(
        "Ingested box score for MLB game mlb_game_id=%s (%s): %d player stat row(s)",
        mlb_game_id,
        status.value,
        upserted,
    )
    return upserted


# --- full ingest orchestration (Req 6.5) ------------------------------------


@dataclass
class MLBIngestSummary:
    """Outcome of one full MLB ingestion run.

    Captures the teams and games synced and, for the box-score batch, the games
    that ingested successfully versus those whose box-score fetch signaled a
    failure (:class:`MLBStatsAPIError`). The per-game failure list makes the
    batch-resilience behavior (Req 6.5) observable: a failed game is recorded
    here while the remaining games still appear in ``box_scores_ingested``.
    """

    teams_synced: int = 0
    games_synced: int = 0
    box_scores_ingested: int = 0
    stat_rows_upserted: int = 0
    failed_game_ids: list[int] = field(default_factory=list)


def run_full_mlb_ingest(
    session: Session,
    client: MLBStatsAPIClient,
    *,
    window_days: int | None = None,
) -> MLBIngestSummary:
    """Run the full MLB ingestion pipeline with per-game batch resilience.

    Wires the ingestion stages in order (per the design data flow):

    1. ``sync_teams``    -- upsert current MLB teams (Req 3.1).
    2. ``sync_rosters``  -- upsert each team's roster (Req 3.2-3.5).
    3. ``sync_schedule`` -- upsert the scheduled games for the window (Req 4.1-4.6).
    4. per-game ``ingest_box_score_for_game`` -- upsert box-score stats (Req 5.1-5.6).

    The box-score stage is the batch: each game is ingested individually and a
    :class:`MLBStatsAPIError` signaled by the client for one game is caught,
    logged, and recorded, after which the remaining games in the batch are still
    processed (Req 6.5). Failures raised by the team/roster/schedule stages are
    *not* swallowed here; they propagate to the worker, which logs them and
    reschedules the next run.

    ``window_days`` defaults to the configured ``MLB_SCHEDULE_MAX_DAYS`` and is
    clamped by ``sync_schedule``. Returns an :class:`MLBIngestSummary` describing
    the run.
    """
    if window_days is None:
        window_days = get_schedule_max_days()

    summary = MLBIngestSummary()

    teams_by_mlb_id = sync_teams(session, client)
    summary.teams_synced = len(teams_by_mlb_id)

    sync_rosters(session, client, teams_by_mlb_id)

    games_by_mlb_id = sync_schedule(session, client, window_days=window_days)
    summary.games_synced = len(games_by_mlb_id)

    # Commit schedule (with final scores) before the slow box-score batch so game
    # markets and prop samples are visible while historical box scores ingest.
    session.commit()

    lookback_days = get_schedule_lookback_days()
    box_score_games = _games_for_box_score_batch(
        session, games_by_mlb_id, lookback_days=lookback_days
    )

    # Box-score batch: one game's signaled failure must not abort the batch (Req 6.5).
    for game in box_score_games:
        mlb_game_id = _safe_positive_int(game.mlb_game_id)
        if mlb_game_id is None:
            continue
        try:
            rows = ingest_box_score_for_game(session, client, game)
            session.commit()
        except MLBStatsAPIError as exc:
            session.rollback()
            # Req 6.5: log the per-game failure and continue with the rest.
            summary.failed_game_ids.append(mlb_game_id)
            logger.warning(
                "Box-score ingestion failed for MLB game mlb_game_id=%s; "
                "continuing with the remaining games in the batch: %s",
                mlb_game_id,
                exc,
            )
            continue
        summary.box_scores_ingested += 1
        summary.stat_rows_upserted += rows

    logger.info(
        "Full MLB ingest complete: %d team(s), %d game(s), "
        "%d box score(s) ingested, %d failed, %d stat row(s)",
        summary.teams_synced,
        summary.games_synced,
        summary.box_scores_ingested,
        len(summary.failed_game_ids),
        summary.stat_rows_upserted,
    )
    return summary
