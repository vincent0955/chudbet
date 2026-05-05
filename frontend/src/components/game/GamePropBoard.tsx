import type { GamePropLinesBundle, PlayerPropLinesRead, StatType } from '../../api/types'
import { useBetSlip } from '../../context/BetSlipContext'
import { formatGameDate, formatHalfPointLine } from '../browse/format'

type Props = {
  bundle: GamePropLinesBundle
}

const PROP_SECTIONS: { stat: StatType; title: string }[] = [
  { stat: 'PTS', title: 'Points' },
  { stat: 'REB', title: 'Rebounds' },
  { stat: 'AST', title: 'Assists' },
]

function lineForStat(player: PlayerPropLinesRead, stat: StatType): number | null {
  if (stat === 'PTS') return player.pts_line
  if (stat === 'REB') return player.reb_line
  return player.ast_line
}

function oddsForStat(player: PlayerPropLinesRead, stat: StatType): { over: string; under: string } {
  if (stat === 'PTS') return { over: player.pts_over_american, under: player.pts_under_american }
  if (stat === 'REB') return { over: player.reb_over_american, under: player.reb_under_american }
  return { over: player.ast_over_american, under: player.ast_under_american }
}

function directionLabel(side: 'OVER' | 'UNDER'): string {
  return side === 'OVER' ? 'Over' : 'Under'
}

function PropPickButtons({
  gameId,
  gameDateLabel,
  player,
  stat,
  line,
  samplesLen,
  overAmerican,
  underAmerican,
}: {
  gameId: number
  gameDateLabel: string
  player: PlayerPropLinesRead
  stat: StatType
  line: number
  samplesLen: number
  overAmerican: string
  underAmerican: string
}) {
  const { addLeg } = useBetSlip()
  const lineLabel = formatHalfPointLine(line)

  const add = (direction: 'OVER' | 'UNDER') => {
    const odds = direction === 'OVER' ? overAmerican : underAmerican
    addLeg(
      {
        player_id: player.id,
        game_id: gameId,
        stat_type: stat,
        line,
        direction,
      },
      {
        primary: `${player.full_name} · ${stat} ${directionLabel(direction)} ${lineLabel} (${odds})`,
        secondary: `${player.team_name} · ${gameDateLabel} · Proj. last ${samplesLen} games`,
      },
    )
  }

  return (
    <div className="game-props__ou">
      <button type="button" className="game-props__ou-btn" onClick={() => add('OVER')}>
        <span className="game-props__ou-btn-label">Over</span>
        <span className="game-props__ou-btn-odds muted">{overAmerican}</span>
      </button>
      <button type="button" className="game-props__ou-btn" onClick={() => add('UNDER')}>
        <span className="game-props__ou-btn-label">Under</span>
        <span className="game-props__ou-btn-odds muted">{underAmerican}</span>
      </button>
    </div>
  )
}

export function GamePropBoard({ bundle }: Props) {
  const { game, lookback, min_samples, players } = bundle
  const ordered = players
  const gameDateLabel = formatGameDate(game.game_date)

  if (ordered.length === 0) {
    return (
      <section className="card game-props game-props--empty">
        <p className="muted">
          No players are linked to these teams in the database yet. Ingest rosters / players to build props here.
        </p>
      </section>
    )
  }

  return (
    <div className="game-props">
      <p className="game-props__explainer muted">
        Showing up to five players per team with the most prior games in our feed (up to {lookback} games each).
        Lines snap to the nearest value ending in .5 from that rolling average (never a whole number like 22.0).
        American odds are simulated for layout only and do not reflect real sportsbook markets.
        At least {min_samples} games with stats are required for a line.
      </p>

      {PROP_SECTIONS.map(({ stat, title }) => (
        <section key={stat} className="card game-props__section" aria-labelledby={`game-props-${stat}-title`}>
          <h2 className="game-props__section-title" id={`game-props-${stat}-title`}>
            {title}
          </h2>

          <div className="game-props__head game-props__head--desktop" aria-hidden>
            <span className="game-props__th game-props__th--player">Player</span>
            <span className="game-props__th game-props__th--line">Line</span>
            <span className="game-props__th game-props__th--pick">Pick</span>
          </div>

          <ul className="game-props__list">
            {ordered.map((player) => {
              const line = lineForStat(player, stat)
              const odds = oddsForStat(player, stat)

              return (
                <li key={`${stat}-${player.id}`} className="game-props__row">
                  <div className="game-props__player">
                    <span className="game-props__name">{player.full_name}</span>
                    <span className="game-props__team muted">{player.team_name}</span>
                  </div>

                  <div className="game-props__line-cell">
                    {line != null ? (
                      <span className="game-props__line-val">{formatHalfPointLine(line)}</span>
                    ) : (
                      <span className="game-props__line-na muted">—</span>
                    )}
                  </div>

                  <div className="game-props__pick-cell">
                    {line != null ? (
                      <PropPickButtons
                        gameId={game.id}
                        gameDateLabel={gameDateLabel}
                        player={player}
                        stat={stat}
                        line={line}
                        samplesLen={player.sample_size}
                        overAmerican={odds.over}
                        underAmerican={odds.under}
                      />
                    ) : (
                      <span className="game-props__pick-na muted">Need ≥{min_samples} prior games</span>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}
