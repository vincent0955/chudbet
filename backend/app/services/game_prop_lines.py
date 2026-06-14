"""Server-side prop line aggregation for a scheduled game (matches frontend rolling-average rules)."""

from __future__ import annotations

from collections import defaultdict
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import GamePropLinesBundle, GameRead, PlayerPropLinesRead
from app.core.config import get_book_margin
from app.db.models import Game, Player, PlayerGameStat, Team

GAME_PROP_LOOKBACK = 10
GAME_PROP_MIN_SAMPLES = 3
BOOK_MARGIN = get_book_margin()


def _half_point_line(values: list[int]) -> float | None:
    """Nearest prop line that **always ends in .5** (never 22.0 — only …21.5, 22.5…)."""
    if len(values) < GAME_PROP_MIN_SAMPLES:
        return None
    avg = sum(values) / len(values)
    return float(round(avg - 0.5) + 0.5)


def _normal_cdf(x: float, mean: float, stddev: float) -> float:
    z = (x - mean) / (stddev * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def _american_from_probability(p: float) -> str:
    if p <= 0.0:
        return "+10000"
    if p >= 1.0:
        return "-10000"
    if p >= 0.5:
        odds = -100.0 * p / (1.0 - p)
    else:
        odds = 100.0 * (1.0 - p) / p
    rounded = int(round(odds))
    return f"+{rounded}" if rounded > 0 else str(rounded)


def _apply_two_way_margin(p_over_fair: float, margin: float = BOOK_MARGIN) -> tuple[float, float]:
    """
    Apply house margin to a fair two-way market.

    Margin system is calibrated so with `margin=0.14`, a 50/50 market prices to -114/-114.
    """
    # Overround multiplier; for 0.14 this is 1.06542056... => 0.53271028 each on coinflip.
    overround = 1.0 + (margin / (2.0 + margin))
    p_over = p_over_fair * overround
    p_under = (1.0 - p_over_fair) * overround

    # Guardrails for extreme tails.
    max_side = 0.999
    min_side = 0.001
    if p_over >= max_side:
        p_over = max_side
        p_under = max(min_side, min(max_side, overround - p_over))
    elif p_under >= max_side:
        p_under = max_side
        p_over = max(min_side, min(max_side, overround - p_under))
    else:
        p_over = max(min_side, p_over)
        p_under = max(min_side, p_under)

    return (p_over, p_under)


def _american_odds_pair_from_history(values: list[int], line: float | None) -> tuple[str, str]:
    """Compute fair O/U American odds from normal approximation of prior game stats."""
    if line is None or len(values) < GAME_PROP_MIN_SAMPLES:
        return ("-110", "-110")
    mean = sum(values) / len(values)
    if len(values) > 1:
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        stddev = math.sqrt(max(variance, 0.0))
    else:
        stddev = 0.0
    stddev = max(stddev, 1.0)

    # For half-point lines there is no push; use strict over probability.
    p_over = 1.0 - _normal_cdf(line, mean, stddev)
    p_over = min(max(p_over, 0.02), 0.98)
    p_over, p_under = _apply_two_way_margin(p_over)
    return (_american_from_probability(p_over), _american_from_probability(p_under))


def build_game_prop_lines_bundle(db: Session, game: Game) -> GamePropLinesBundle:
    roster_rows = db.execute(
        select(Player, Team.name, Team.nba_team_id)
        .join(Team, Player.team_id == Team.id)
        .where(Player.team_id.in_((game.home_team_id, game.away_team_id)))
        .order_by(Player.team_id.asc(), Player.full_name.asc())
    ).all()

    player_ids = [p.id for p, _, _ in roster_rows]
    by_player: dict[int, list[PlayerGameStat]] = defaultdict(list)

    if player_ids:
        stmt = (
            select(PlayerGameStat)
            .join(Game, PlayerGameStat.game_id == Game.id)
            .where(
                PlayerGameStat.player_id.in_(player_ids),
                Game.game_date < game.game_date,
                PlayerGameStat.game_id != game.id,
            )
            .order_by(PlayerGameStat.player_id.asc(), Game.game_date.desc(), Game.id.desc())
        )
        for stat in db.scalars(stmt):
            bucket = by_player[stat.player_id]
            if len(bucket) >= GAME_PROP_LOOKBACK:
                continue
            bucket.append(stat)

    players_build: list[PlayerPropLinesRead] = []
    for player, team_name, team_nba_id in roster_rows:
        samples = by_player.get(player.id, [])
        n = len(samples)
        pts_vals = [s.points for s in samples]
        reb_vals = [s.rebounds for s in samples]
        ast_vals = [s.assists for s in samples]

        pts_line = _half_point_line(pts_vals)
        reb_line = _half_point_line(reb_vals)
        ast_line = _half_point_line(ast_vals)
        po, pu = _american_odds_pair_from_history(pts_vals, pts_line)
        ro, ru = _american_odds_pair_from_history(reb_vals, reb_line)
        ao, au = _american_odds_pair_from_history(ast_vals, ast_line)

        players_build.append(
            PlayerPropLinesRead(
                id=player.id,
                full_name=player.full_name,
                team_id=player.team_id,
                team_name=team_name,
                team_nba_id=team_nba_id,
                nba_player_id=player.nba_player_id,
                sample_size=n,
                pts_line=pts_line,
                reb_line=reb_line,
                ast_line=ast_line,
                pts_over_american=po,
                pts_under_american=pu,
                reb_over_american=ro,
                reb_under_american=ru,
                ast_over_american=ao,
                ast_under_american=au,
            )
        )

    players_out = sorted(players_build, key=lambda r: (r.team_name.lower(), r.full_name.lower()))

    return GamePropLinesBundle(
        game=GameRead.model_validate(game),
        lookback=GAME_PROP_LOOKBACK,
        min_samples=GAME_PROP_MIN_SAMPLES,
        players=players_out,
    )
