import { useState } from 'react'
import type {
  MLBGamePropLinesBundle,
  MLBPlayerPropLinesRead,
  MLBPropStatLineRead,
  MLBStatType,
} from '../../api/types'
import { parseAmericanOddsString } from '../../utils/parlayOdds'
import { useBetSlip } from '../../context/BetSlipContext'
import { mlbPlayerHeadshotUrl, mlbTeamLogoUrl } from '../../lib/mlbMedia'
import { formatHalfPointLine } from '../browse/format'

type Props = {
  bundle: MLBGamePropLinesBundle
  slipGameHeader?: string
  wageringLocked?: boolean
}

const MLB_STAT_SECTIONS: { stat: MLBStatType; title: string }[] = [
  { stat: 'HITS', title: 'Hits' },
  { stat: 'TOTAL_BASES', title: 'Total Bases' },
  { stat: 'RBI', title: 'RBI' },
  { stat: 'RUNS', title: 'Runs' },
  { stat: 'STRIKEOUTS_PITCHER', title: 'Pitcher Ks' },
]

function statLineFor(player: MLBPlayerPropLinesRead, stat: MLBStatType): MLBPropStatLineRead | null {
  return player.stat_lines.find((s) => s.stat_type === stat) ?? null
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
  disabled,
}: {
  gameId: number
  slipGameHeader?: string
  player: MLBPlayerPropLinesRead
  stat: MLBStatType
  line: number
  overAmerican: string
  underAmerican: string
  disabled?: boolean
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
    if (disabled) return
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
        disabled={disabled}
      >
        <span className="game-props__ou-btn-label">O {lineLabel}</span>
        <span className="game-props__ou-btn-odds muted">{overAmerican}</span>
      </button>
      <button
        type="button"
        className={`game-props__ou-btn${underSelected ? ' game-props__ou-btn--selected' : ''}`}
        onClick={() => toggle('UNDER')}
        aria-pressed={underSelected}
        disabled={disabled}
      >
        <span className="game-props__ou-btn-label">U {lineLabel}</span>
        <span className="game-props__ou-btn-odds muted">{underAmerican}</span>
      </button>
    </div>
  )
}

function PlayerHeadshot({
  player,
}: {
  player: MLBPlayerPropLinesRead
}) {
  const headshotUrl = mlbPlayerHeadshotUrl(player.mlb_player_id)
  const badgeUrl = mlbTeamLogoUrl(player.mlb_team_id)
  const [headshotBroken, setHeadshotBroken] = useState(false)
  const [badgeBroken, setBadgeBroken] = useState(false)

  return (
    <span className="game-props__headshot-wrap">
      {headshotUrl && !headshotBroken ? (
        <img
          className="game-props__headshot"
          src={headshotUrl}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setHeadshotBroken(true)}
        />
      ) : (
        <span className="game-props__headshot game-props__headshot--placeholder" aria-hidden />
      )}
      {badgeUrl && !badgeBroken ? (
        <img
          className="game-props__headshot-team-badge"
          src={badgeUrl}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setBadgeBroken(true)}
        />
      ) : null}
    </span>
  )
}

export function MLBPropBoard({ bundle, slipGameHeader, wageringLocked }: Props) {
  const { game, players } = bundle
  const offeredStats = MLB_STAT_SECTIONS.filter(({ stat }) =>
    players.some((p) => statLineFor(p, stat) != null),
  )

  function topPlayersForStat(stat: MLBStatType): MLBPlayerPropLinesRead[] {
    const ranked = [...players]
      .filter((p) => statLineFor(p, stat) != null)
      .sort((a, b) => {
        const aLine = statLineFor(a, stat)?.line ?? -Infinity
        const bLine = statLineFor(b, stat)?.line ?? -Infinity
        if (aLine !== bLine) return bLine - aLine
        if (a.sample_size !== b.sample_size) return b.sample_size - a.sample_size
        return a.full_name.localeCompare(b.full_name)
      })
    const awayTop = ranked.filter((p) => p.team_id === game.away_team_id).slice(0, 5)
    const homeTop = ranked.filter((p) => p.team_id === game.home_team_id).slice(0, 5)
    return [...awayTop, ...homeTop]
  }

  if (players.length === 0) {
    return (
      <section className="card game-props game-props--empty">
        <p className="muted">No MLB content available</p>
      </section>
    )
  }

  if (offeredStats.length === 0) {
    return (
      <section className="card game-props game-props--empty">
        <p className="muted">No eligible MLB prop markets for this game yet.</p>
      </section>
    )
  }

  return (
    <div className="game-props">
      {wageringLocked && (
        <div className="card game-props__locked-banner" role="status">
          <p className="muted">This game is in progress or finished — new picks are disabled.</p>
        </div>
      )}
      {offeredStats.map(({ stat, title }) => {
        const sectionPlayers = topPlayersForStat(stat)
        return (
          <details key={stat} className="card game-props__section" open>
            <summary className="game-props__section-summary">
              <h2 className="game-props__section-title" id={`mlb-props-${stat}-title`}>
                {title}
              </h2>
            </summary>

            <div className="game-props__section-body">
              <ul className="game-props__list">
                {sectionPlayers.length === 0 && (
                  <li className="game-props__row">
                    <span className="game-props__pick-na muted">No eligible players yet for this market.</span>
                  </li>
                )}
                {sectionPlayers.map((player) => {
                  const lineEntry = statLineFor(player, stat)
                  if (!lineEntry) return null
                  return (
                    <li key={`${stat}-${player.id}`} className="game-props__row">
                      <div className="game-props__player">
                        <PlayerHeadshot player={player} />
                        <span className="game-props__name">{player.full_name}</span>
                        <span className="game-props__team muted">{player.team_name}</span>
                      </div>
                      <div className="game-props__pick-cell">
                        <PropPickButtons
                          gameId={game.id}
                          slipGameHeader={slipGameHeader}
                          player={player}
                          stat={stat}
                          line={lineEntry.line}
                          overAmerican={lineEntry.over_american}
                          underAmerican={lineEntry.under_american}
                          disabled={wageringLocked}
                        />
                      </div>
                    </li>
                  )
                })}
              </ul>
            </div>
          </details>
        )
      })}
    </div>
  )
}
