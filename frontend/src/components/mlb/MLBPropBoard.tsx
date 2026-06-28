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

/** Implied (with-vig) probability for an American-odds string; 0 when unparseable. */
function impliedProbability(american: string): number {
  const n = parseAmericanOddsString(american)
  if (n == null || n === 0) return 0
  return n > 0 ? 100 / (n + 100) : Math.abs(n) / (Math.abs(n) + 100)
}

/** Rank metric for a stat line: summed milestone likelihood (proxy for projected volume). */
function statStrength(line: MLBPropStatLineRead): number {
  return line.thresholds.reduce((acc, t) => acc + impliedProbability(t.american), 0)
}

/**
 * Milestone ("N+") picker. Each offered threshold is its own market with its own
 * price; selecting one deselects any other milestone for the same player/stat so
 * a single pick stays active at a time. Each milestone is stored on the slip as
 * an OVER leg at `threshold - 0.5`, matching how the server settles it.
 */
function PropPickButtons({
  gameId,
  slipGameHeader,
  player,
  stat,
  statTitle,
  entry,
  disabled,
}: {
  gameId: number
  slipGameHeader?: string
  player: MLBPlayerPropLinesRead
  stat: MLBStatType
  statTitle: string
  entry: MLBPropStatLineRead
  disabled?: boolean
}) {
  const { addLeg, hasLeg, removeLegByLeg } = useBetSlip()

  const legFor = (line: number) => ({
    player_id: player.id,
    game_id: gameId,
    stat_type: stat,
    line,
    direction: 'OVER' as const,
  })

  const toggle = (threshold: number, american: string) => {
    if (disabled) return
    const leg = legFor(threshold - 0.5)
    if (hasLeg({ kind: 'player', leg })) {
      removeLegByLeg({ kind: 'player', leg })
      return
    }
    // Keep at most one milestone per player/stat selected.
    for (const other of entry.thresholds) {
      if (other.threshold === threshold) continue
      removeLegByLeg({ kind: 'player', leg: legFor(other.threshold - 0.5) })
    }
    addLeg(
      { kind: 'player', leg },
      {
        playerLine: player.full_name,
        propLine: `${statTitle} ${threshold}+`,
        gameSlipHeader: slipGameHeader ?? null,
      },
      parseAmericanOddsString(american),
    )
  }

  return (
    <div className="game-props__ou">
      {entry.thresholds.map((t) => {
        const selected = hasLeg({ kind: 'player', leg: legFor(t.threshold - 0.5) })
        return (
          <button
            key={t.threshold}
            type="button"
            className={`game-props__ou-btn${selected ? ' game-props__ou-btn--selected' : ''}`}
            onClick={() => toggle(t.threshold, t.american)}
            aria-pressed={selected}
            disabled={disabled}
          >
            <span className="game-props__ou-btn-label">{t.threshold}+</span>
            <span className="game-props__ou-btn-odds muted">{t.american}</span>
          </button>
        )
      })}
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
        const aStrength = statStrength(statLineFor(a, stat)!)
        const bStrength = statStrength(statLineFor(b, stat)!)
        if (aStrength !== bStrength) return bStrength - aStrength
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
                          statTitle={title}
                          entry={lineEntry}
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
