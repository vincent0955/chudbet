import type { GamePropLinesBundle, PlayerPropLinesRead, StatType } from '../../api/types'
import { parseAmericanOddsString } from '../../utils/parlayOdds'
import { useBetSlip } from '../../context/BetSlipContext'
import { nbaPlayerHeadshotUrl, nbaTeamLogoUrl } from '../../lib/nbaMedia'
import { formatHalfPointLine } from '../browse/format'

type Props = {
  bundle: GamePropLinesBundle
  /** Matchup + date for bet slip grouping (same for every leg from this board). */
  slipGameHeader?: string
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
  return side === 'OVER' ? 'OVER' : 'UNDER'
}

function PropPickButtons({
  gameId,
  slipGameHeader,
  player,
  stat,
  line,
  overAmerican,
  underAmerican,
}: {
  gameId: number
  slipGameHeader?: string
  player: PlayerPropLinesRead
  stat: StatType
  line: number
  overAmerican: string
  underAmerican: string
}) {
  const { addLeg, hasLeg, removeLegByLeg } = useBetSlip()
  const lineLabel = formatHalfPointLine(line)
  const overLeg = {
    player_id: player.id,
    game_id: gameId,
    stat_type: stat,
    line,
    direction: 'OVER' as const,
  }
  const underLeg = {
    player_id: player.id,
    game_id: gameId,
    stat_type: stat,
    line,
    direction: 'UNDER' as const,
  }
  const overSelected = hasLeg({ kind: 'player', leg: overLeg })
  const underSelected = hasLeg({ kind: 'player', leg: underLeg })

  const toggle = (direction: 'OVER' | 'UNDER') => {
    const leg = direction === 'OVER' ? overLeg : underLeg
    const opposite = direction === 'OVER' ? underLeg : overLeg
    if (hasLeg({ kind: 'player', leg })) {
      removeLegByLeg({ kind: 'player', leg })
      return
    }
    if (hasLeg({ kind: 'player', leg: opposite })) {
      removeLegByLeg({ kind: 'player', leg: opposite })
    }
    const odds = direction === 'OVER' ? overAmerican : underAmerican
    addLeg(
      { kind: 'player', leg },
      {
        playerLine: player.full_name,
        propLine: `${stat} ${directionLabel(direction)} ${lineLabel}`,
        gameSlipHeader: slipGameHeader ?? null,
      },
      parseAmericanOddsString(odds),
    )
  }

  return (
    <div className="game-props__ou">
      <button
        type="button"
        className={`game-props__ou-btn${overSelected ? ' game-props__ou-btn--selected' : ''}`}
        onClick={() => toggle('OVER')}
        aria-pressed={overSelected}
      >
        <span className="game-props__ou-btn-label">O {lineLabel}</span>
        <span className="game-props__ou-btn-odds muted">{overAmerican}</span>
      </button>
      <button
        type="button"
        className={`game-props__ou-btn${underSelected ? ' game-props__ou-btn--selected' : ''}`}
        onClick={() => toggle('UNDER')}
        aria-pressed={underSelected}
      >
        <span className="game-props__ou-btn-label">U {lineLabel}</span>
        <span className="game-props__ou-btn-odds muted">{underAmerican}</span>
      </button>
    </div>
  )
}

export function GamePropBoard({ bundle, slipGameHeader }: Props) {
  const { game, min_samples, players } = bundle
  const ordered = players

  function topPlayersForStat(stat: StatType): PlayerPropLinesRead[] {
    const ranked = [...ordered]
      .filter((p) => lineForStat(p, stat) != null)
      .sort((a, b) => {
        const aLine = lineForStat(a, stat) ?? -Infinity
        const bLine = lineForStat(b, stat) ?? -Infinity
        if (aLine !== bLine) return bLine - aLine
        if (a.sample_size !== b.sample_size) return b.sample_size - a.sample_size
        return a.full_name.localeCompare(b.full_name)
      })
    const awayTop = ranked.filter((p) => p.team_id === game.away_team_id).slice(0, 5)
    const homeTop = ranked.filter((p) => p.team_id === game.home_team_id).slice(0, 5)
    return [...awayTop, ...homeTop]
  }

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
      {PROP_SECTIONS.map(({ stat, title }) => {
        const sectionPlayers = topPlayersForStat(stat)
        return (
        <details key={stat} className="card game-props__section" open>
          <summary className="game-props__section-summary">
            <h2 className="game-props__section-title" id={`game-props-${stat}-title`}>
              {title}
            </h2>
          </summary>

          <div className="game-props__section-body">
            <div className="game-props__head game-props__head--desktop" aria-hidden>
              <span className="game-props__th game-props__th--player">Player</span>
              <span className="game-props__th game-props__th--pick">
                <span>Over</span>
                <span>Under</span>
              </span>
            </div>

            <ul className="game-props__list">
              {sectionPlayers.length === 0 && (
                <li className="game-props__row">
                  <span className="game-props__pick-na muted">No eligible players yet for this market.</span>
                </li>
              )}
              {sectionPlayers.map((player) => {
                const line = lineForStat(player, stat)
                const odds = oddsForStat(player, stat)

                return (
                  <li key={`${stat}-${player.id}`} className="game-props__row">
                    <div className="game-props__player">
                      {nbaPlayerHeadshotUrl(player.nba_player_id) && (
                        <span className="game-props__headshot-wrap">
                          <img
                            className="game-props__headshot"
                            src={nbaPlayerHeadshotUrl(player.nba_player_id) ?? ''}
                            alt=""
                            loading="lazy"
                            decoding="async"
                          />
                          {nbaTeamLogoUrl(player.team_nba_id) && (
                            <img
                              className="game-props__headshot-team-badge"
                              src={nbaTeamLogoUrl(player.team_nba_id) ?? ''}
                              alt=""
                              loading="lazy"
                              decoding="async"
                            />
                          )}
                        </span>
                      )}
                      <span className="game-props__name">{player.full_name}</span>
                      <span className="game-props__team muted">{player.team_name}</span>
                    </div>

                    <div className="game-props__pick-cell">
                      {line != null ? (
                        <PropPickButtons
                          gameId={game.id}
                          slipGameHeader={slipGameHeader}
                          player={player}
                          stat={stat}
                          line={line}
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
          </div>
        </details>
      )})}
    </div>
  )
}
