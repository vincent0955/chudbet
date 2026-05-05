"""Server-side prop line aggregation for a scheduled game (matches frontend rolling-average rules)."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import GamePropLinesBundle, GameRead, PlayerPropLinesRead
from app.db.models import Game, Player, PlayerGameStat, Team

GAME_PROP_LOOKBACK = 10
GAME_PROP_MIN_SAMPLES = 3
TOP_PLAYERS_PER_TEAM = 5


def _half_point_line(values: list[int]) -> float | None:
    """Nearest prop line that **always ends in .5** (never 22.0 — only …21.5, 22.5…)."""
    if len(values) < GAME_PROP_MIN_SAMPLES:
        return None
    avg = sum(values) / len(values)
    return float(round(avg - 0.5) + 0.5)


def _american_odds_pair(seed: int) -> tuple[str, str]:
    """Simulated American odds for UI only — not live sportsbook prices."""
    s = abs(seed) % 10_007
    over_am = -102 - (s % 19)
    under_am = over_am - 2 - ((s // 19) % 9)
    return (str(over_am), str(under_am))


def _odds_seed(player_id: int, stat: str) -> int:
    return player_id * 131 + sum(ord(c) for c in stat) * 17


def build_game_prop_lines_bundle(db: Session, game: Game) -> GamePropLinesBundle:
    roster_rows = db.execute(
        select(Player, Team.name)
        .join(Team, Player.team_id == Team.id)
        .where(Player.team_id.in_((game.home_team_id, game.away_team_id)))
        .order_by(Player.team_id.asc(), Player.full_name.asc())
    ).all()

    player_ids = [p.id for p, _ in roster_rows]
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
    for player, team_name in roster_rows:
        samples = by_player.get(player.id, [])
        n = len(samples)
        pts_vals = [s.points for s in samples]
        reb_vals = [s.rebounds for s in samples]
        ast_vals = [s.assists for s in samples]

        po, pu = _american_odds_pair(_odds_seed(player.id, "PTS"))
        ro, ru = _american_odds_pair(_odds_seed(player.id, "REB"))
        ao, au = _american_odds_pair(_odds_seed(player.id, "AST"))

        players_build.append(
            PlayerPropLinesRead(
                id=player.id,
                full_name=player.full_name,
                team_id=player.team_id,
                team_name=team_name,
                nba_player_id=player.nba_player_id,
                sample_size=n,
                pts_line=_half_point_line(pts_vals),
                reb_line=_half_point_line(reb_vals),
                ast_line=_half_point_line(ast_vals),
                pts_over_american=po,
                pts_under_american=pu,
                reb_over_american=ro,
                reb_under_american=ru,
                ast_over_american=ao,
                ast_under_american=au,
            )
        )

    by_tid: dict[int, list[PlayerPropLinesRead]] = defaultdict(list)
    for row in players_build:
        by_tid[row.team_id].append(row)

    def pick_top(team_id: int) -> list[PlayerPropLinesRead]:
        rows = by_tid.get(team_id, [])
        rows = sorted(rows, key=lambda r: (-r.sample_size, r.full_name.lower()))
        return rows[:TOP_PLAYERS_PER_TEAM]

    players_out = pick_top(game.away_team_id) + pick_top(game.home_team_id)

    return GamePropLinesBundle(
        game=GameRead.model_validate(game),
        lookback=GAME_PROP_LOOKBACK,
        min_samples=GAME_PROP_MIN_SAMPLES,
        players=players_out,
    )
