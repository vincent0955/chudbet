"""MLB player-prop line aggregation for a scheduled game (Requirement 9).

For each rostered player on both teams of the target MLB game this service
produces a prop line plus over/under American odds for every ``MLBStatType``
applicable to that player:

- ``STRIKEOUTS_PITCHER`` for pitchers, and
- ``HITS`` / ``TOTAL_BASES`` / ``RBI`` / ``RUNS`` for non-pitchers,

keyed off the player's ``primary_position`` (Req 9.1).

Baseball props use an "N-or-more" milestone ladder rather than a single
over/under line: each offered stat exposes the fixed thresholds ``1+``, ``2+``,
and ``3+``, each with its own price. Each threshold's probability is modeled as
``P(X >= threshold)`` for a Poisson distribution whose rate is the player's
rolling per-game average of that stat over prior MLB games within
``MLB_PROP_LOOKBACK_DAYS`` (Req 9.2); Poisson fits discrete counting stats far
better than a normal approximation. A stat with fewer prior games than
``MLB_PROP_MIN_SAMPLES`` is omitted entirely, with no odds (Req 9.3). The
configured house margin makes each milestone's two-way (reaches / does-not-reach)
implied probabilities sum to strictly more than 1 (Req 9.4). Samples derive only
from MLB games before the target game's date, excluding the target game itself
(Req 9.5).

Each milestone is stored on a wager leg as ``line = threshold - 0.5`` with an
``OVER`` direction so the existing ``value > line`` settlement grades ``N+``
correctly (e.g. ``2+`` hits == OVER 1.5 == ``hits >= 2``).

This module imports the league-neutral odds math from ``app.services.odds_math``
only; it holds the baseball-specific stat vocabulary and applicability rules.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    MLBGamePropLinesBundle,
    MLBGameRead,
    MLBPlayerPropLinesRead,
    MLBPropStatLineRead,
    MLBPropThresholdRead,
)
from app.db.enums import Sport
from app.db.models import Game, MLBPlayerGameStat, Player, Team
from app.mlb.config import get_prop_lookback_days, get_prop_max_games, get_prop_min_samples
from app.mlb.enums import MLBStatType
from app.services.odds_math import (
    american_from_probability,
    apply_two_way_margin_balanced,
    poisson_at_least,
)

# Fixed "N-or-more" milestones offered for every MLB prop stat (Req: 1+/2+/3+).
MLB_PROP_THRESHOLDS: tuple[int, ...] = (1, 2, 3)

# Floor for the Poisson rate so a player with an all-zero (but qualifying)
# history still produces finite, bettable long-shot odds instead of +inf.
_MIN_POISSON_RATE = 0.05

# Maps each MLB stat type to the column it reads on ``MLBPlayerGameStat``.
_STAT_COLUMNS: dict[MLBStatType, str] = {
    MLBStatType.HITS: "hits",
    MLBStatType.TOTAL_BASES: "total_bases",
    MLBStatType.RBI: "rbi",
    MLBStatType.RUNS: "runs",
    MLBStatType.STRIKEOUTS_PITCHER: "strikeouts_pitcher",
}

# Stats applicable to non-pitchers, in display order.
_BATTER_STATS: tuple[MLBStatType, ...] = (
    MLBStatType.HITS,
    MLBStatType.TOTAL_BASES,
    MLBStatType.RBI,
    MLBStatType.RUNS,
)
# Stats applicable to pitchers, in display order.
_PITCHER_STATS: tuple[MLBStatType, ...] = (MLBStatType.STRIKEOUTS_PITCHER,)

# Position tokens (case-insensitive) that identify a pitcher.
_PITCHER_TOKENS = {"P", "SP", "RP", "LHP", "RHP"}


def _is_pitcher(primary_position: str | None) -> bool:
    """Return whether a roster ``primary_position`` denotes a pitcher.

    Handles position abbreviations (``"P"``, ``"SP"``, ``"RP"`` ...) as well as
    position type/name fallbacks that contain "pitch" (e.g. ``"Pitcher"``).
    """
    if not primary_position:
        return False
    token = primary_position.strip().upper()
    if token in _PITCHER_TOKENS:
        return True
    return "PITCH" in token


def _applicable_stats(primary_position: str | None) -> tuple[MLBStatType, ...]:
    """Return the stat types offered for a player based on roster position (Req 9.1)."""
    return _PITCHER_STATS if _is_pitcher(primary_position) else _BATTER_STATS


def _threshold_ladder(values: list[int]) -> list[MLBPropThresholdRead]:
    """Build the ``1+``/``2+``/``3+`` milestone ladder for one stat's history.

    The Poisson rate is the player's rolling per-game average. For each
    threshold the fair "reaches N+" probability is ``P(X >= N)``; the house
    margin is applied to the two-way (reaches / does-not-reach) market so the
    displayed price carries the book's overround.
    """
    lam = max(sum(values) / len(values), _MIN_POISSON_RATE)

    ladder: list[MLBPropThresholdRead] = []
    for threshold in MLB_PROP_THRESHOLDS:
        p_yes_fair = poisson_at_least(threshold, lam)
        p_yes, p_no = apply_two_way_margin_balanced(p_yes_fair)
        ladder.append(
            MLBPropThresholdRead(
                threshold=threshold,
                line=float(threshold) - 0.5,
                american=american_from_probability(p_yes),
                under_american=american_from_probability(p_no),
            )
        )
    return ladder


def build_mlb_game_prop_lines_bundle(db: Session, game: Game) -> MLBGamePropLinesBundle:
    """Build the MLB player-prop bundle for ``game`` (Requirement 9)."""
    lookback_days = get_prop_lookback_days()
    min_samples = get_prop_min_samples()
    max_games = get_prop_max_games()

    roster_rows = db.execute(
        select(Player, Team.name, Team.mlb_team_id)
        .join(Team, Player.team_id == Team.id)
        .where(Player.team_id.in_((game.home_team_id, game.away_team_id)))
        .order_by(Player.team_id.asc(), Player.full_name.asc())
    ).all()

    player_ids = [p.id for p, _, _ in roster_rows]
    by_player: dict[int, list[MLBPlayerGameStat]] = defaultdict(list)

    if player_ids:
        cutoff_date = game.game_date - timedelta(days=lookback_days)
        stmt = (
            select(MLBPlayerGameStat)
            .join(Game, MLBPlayerGameStat.game_id == Game.id)
            .where(
                MLBPlayerGameStat.player_id.in_(player_ids),
                MLBPlayerGameStat.game_id != game.id,
                Game.sport == Sport.MLB,
                Game.game_date < game.game_date,
                Game.game_date >= cutoff_date,
            )
            .order_by(MLBPlayerGameStat.player_id.asc(), Game.game_date.desc(), Game.id.desc())
        )
        for stat in db.scalars(stmt):
            bucket = by_player[stat.player_id]
            if len(bucket) >= max_games:
                continue
            bucket.append(stat)

    players_build: list[MLBPlayerPropLinesRead] = []
    for player, team_name, team_mlb_id in roster_rows:
        samples = by_player.get(player.id, [])
        n = len(samples)

        stat_lines: list[MLBPropStatLineRead] = []
        for stat_type in _applicable_stats(player.primary_position):
            # Req 9.3: omit a stat (and its odds) below the minimum sample size.
            if n < min_samples:
                continue
            column = _STAT_COLUMNS[stat_type]
            values = [getattr(s, column) for s in samples]
            stat_lines.append(
                MLBPropStatLineRead(
                    stat_type=stat_type.value,
                    thresholds=_threshold_ladder(values),
                )
            )

        players_build.append(
            MLBPlayerPropLinesRead(
                id=player.id,
                full_name=player.full_name,
                team_id=player.team_id,
                team_name=team_name,
                mlb_team_id=team_mlb_id,
                mlb_player_id=player.mlb_player_id,
                primary_position=player.primary_position,
                sample_size=n,
                stat_lines=stat_lines,
            )
        )

    players_out = sorted(players_build, key=lambda r: (r.team_name.lower(), r.full_name.lower()))

    return MLBGamePropLinesBundle(
        game=MLBGameRead.model_validate(game),
        lookback_days=lookback_days,
        min_samples=min_samples,
        players=players_out,
    )
