import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, getParlay } from '../api'
import type { ParlayGameLegRead, ParlayLegOutcome, ParlayLegRead, ParlayRead } from '../api/types'
import { formatHalfPointLine } from '../components/browse/format'
import { formatUsdFromCents } from '../lib/formatMoney'
import { nbaPlayerHeadshotUrl, nbaTeamLogoUrl } from '../lib/nbaMedia'
import { decimalToAmerican, formatAmericanOdds } from '../utils/parlayOdds'

function legOutcomeLabel(o: ParlayLegOutcome | null | undefined): string {
  switch (o ?? 'pending') {
    case 'pending':
      return 'Leg pending'
    case 'hit':
      return 'Leg hit'
    case 'miss':
      return 'Leg missed'
    case 'void':
      return 'Leg void — no result'
    default:
      return 'Leg pending'
  }
}

function LegOutcomeIcon({ outcome }: { outcome?: ParlayLegOutcome | null }) {
  const o = outcome ?? 'pending'
  const label = legOutcomeLabel(o)
  const circle = (
    <circle cx="12" cy="12" r="9.25" fill="none" stroke="currentColor" strokeWidth="1.75" />
  )

  if (o === 'hit') {
    return (
      <svg
        className="parlay-leg__status parlay-leg__status--hit"
        width={28}
        height={28}
        viewBox="0 0 24 24"
        aria-hidden={false}
        role="img"
        aria-label={label}
      >
        {circle}
        <path
          d="M7.25 12.25 10.5 15.5 17.25 8.25"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  }

  if (o === 'miss') {
    return (
      <svg
        className="parlay-leg__status parlay-leg__status--miss"
        width={28}
        height={28}
        viewBox="0 0 24 24"
        aria-hidden={false}
        role="img"
        aria-label={label}
      >
        {circle}
        <path
          d="M8 8 16 16M16 8 8 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    )
  }

  /* pending + void: neutral symbol inside circle */
  return (
    <svg
      className={`parlay-leg__status parlay-leg__status--neutral${o === 'void' ? ' parlay-leg__status--void' : ''}`}
      width={28}
      height={28}
      viewBox="0 0 24 24"
      aria-hidden={false}
      role="img"
      aria-label={label}
    >
      {circle}
      <line x1="7.5" y1="12" x2="16.5" y2="12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

function formatLegSummary(leg: ParlayLegRead): string {
  const name = leg.player_full_name?.trim() || `Player #${leg.player_id}`
  const line = formatHalfPointLine(leg.line)
  return `${name} · ${leg.stat_type} ${leg.direction} ${line}`
}

function formatGameLegSummary(leg: ParlayGameLegRead): string {
  const game = leg.game_label || `Game #${leg.game_id}`
  const homeTeam = leg.home_team_name || 'Home'
  const awayTeam = leg.away_team_name || 'Away'
  const odds = `${leg.odds_american >= 0 ? '+' : ''}${leg.odds_american}`
  if (leg.market_type === 'moneyline') {
    const team =
      leg.selection === 'home'
        ? homeTeam
        : leg.selection === 'away'
          ? awayTeam
          : leg.selection.toUpperCase()
    return `${team} · MONEYLINE (${odds})`
  }
  if (leg.market_type === 'spread') {
    const line = leg.line ?? 0
    const team = leg.selection === 'home' ? homeTeam : awayTeam
    return `${team} · SPREAD ${line >= 0 ? '+' : ''}${line.toFixed(1)} (${odds})`
  }
  const line = leg.line ?? 0
  const side = leg.selection === 'over' ? 'OVER' : 'UNDER'
  return `${game} · TOTAL ${side} ${line.toFixed(1)} (${odds})`
}

type GroupRow = {
  key: string
  outcome?: ParlayLegOutcome | null
  text: string
  kind: 'player' | 'game'
  direction?: 'OVER' | 'UNDER'
  line?: number
  statValue?: number | null
  playerImageUrl?: string | null
  playerTeamLogoUrl?: string | null
}

type Group = {
  game: string
  scoreLabel?: string
  scoreIsFinal?: boolean
  rows: GroupRow[]
}

const PROGRESS_THRESHOLD_PCT = 80

function isFinalStatus(status: string | null | undefined): boolean {
  return (status ?? '').toLowerCase().includes('final')
}

function buildGroups(p: ParlayRead): Group[] {
  const map = new Map<string, GroupRow[]>()
  const scoreByGame = new Map<string, string | undefined>()
  const finalByGame = new Map<string, boolean>()
  const order: string[] = []
  const push = (game: string, row: GroupRow, gameStatus?: string | null) => {
    if (!map.has(game)) {
      map.set(game, [])
      order.push(game)
      finalByGame.set(game, false)
    }
    if (isFinalStatus(gameStatus)) {
      finalByGame.set(game, true)
    }
    map.get(game)!.push(row)
  }
  for (const leg of [...p.legs].sort((a, b) => a.sort_order - b.sort_order)) {
    const groupKey = leg.game_label || 'No specific game'
    if (!scoreByGame.has(groupKey) && leg.game_home_score != null && leg.game_away_score != null) {
      scoreByGame.set(groupKey, `${leg.game_away_score} - ${leg.game_home_score}`)
    }
    push(groupKey, {
      key: `player-${leg.id}`,
      outcome: leg.outcome,
      text: formatLegSummary(leg),
      kind: 'player',
      direction: leg.direction,
      line: leg.line,
      statValue: leg.stat_value,
      playerImageUrl: nbaPlayerHeadshotUrl(leg.player_nba_id),
      playerTeamLogoUrl: nbaTeamLogoUrl(leg.player_team_nba_id),
    }, leg.game_status)
  }
  for (const leg of [...(p.game_legs ?? [])].sort((a, b) => a.sort_order - b.sort_order)) {
    const groupKey = leg.game_label || `Game #${leg.game_id}`
    if (!scoreByGame.has(groupKey) && leg.home_score != null && leg.away_score != null) {
      scoreByGame.set(groupKey, `${leg.away_score} - ${leg.home_score}`)
    }
    push(groupKey, {
      key: `game-${leg.id}`,
      outcome: leg.outcome,
      text: formatGameLegSummary(leg),
      kind: 'game',
    }, leg.game_status)
  }
  return order.map((game) => ({
    game,
    scoreLabel: scoreByGame.get(game),
    scoreIsFinal: finalByGame.get(game) ?? false,
    rows: map.get(game)!,
  }))
}

function playerProgressValue(currentValue: number | null | undefined, line: number | undefined): number {
  if (currentValue == null || line == null || line <= 0) return 0
  const ratio = currentValue / line
  if (ratio <= 1) return Math.max(0, Math.min(PROGRESS_THRESHOLD_PCT, ratio * PROGRESS_THRESHOLD_PCT))
  const overflowPct = (ratio - 1) * (100 - PROGRESS_THRESHOLD_PCT)
  return Math.max(PROGRESS_THRESHOLD_PCT, Math.min(100, PROGRESS_THRESHOLD_PCT + overflowPct))
}

function parseId(raw: string | undefined): number | null {
  if (!raw) return null
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) && n > 0 ? n : null
}

type LoadState = { kind: 'loading' } | { kind: 'ok'; data: ParlayRead } | { kind: 'error'; message: string }

function InvalidParlayId() {
  return (
    <div className="page">
      <section className="card">
        <h1 className="page-title">Parlay</h1>
        <p className="status-err">Invalid parlay id in URL.</p>
        <p>
          <Link to="/" className="inline-link">
            Back home
          </Link>
        </p>
      </section>
    </div>
  )
}

/** Loads one parlay; remount via parent `key` when `id` changes so loading state resets without sync setState in effects. */
function ParlayDetailLoaded({ id }: { id: number }) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await getParlay(id)
        if (!cancelled) setState({ kind: 'ok', data })
      } catch (e) {
        if (!cancelled) {
          const message =
            e instanceof ApiError && e.status === 404
              ? 'Parlay not found'
              : e instanceof ApiError
                ? e.message
                : 'Failed to load parlay'
          setState({ kind: 'error', message })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [id])

  if (state.kind === 'error') {
    return (
      <div className="page">
        <section className="card">
          <h1 className="page-title">Parlay</h1>
          <p className="status-err">{state.message}</p>
          <p>
            <Link to="/" className="inline-link">
              Back home
            </Link>
          </p>
        </section>
      </div>
    )
  }

  if (state.kind === 'loading') {
    return (
      <div className="page">
        <section className="card">
          <h1 className="page-title">Parlay #{id}</h1>
          <p className="muted">Loading…</p>
        </section>
      </div>
    )
  }

  const p = state.data
  const groups = buildGroups(p)
  const fairAmerican =
    p.fair_decimal_odds != null && Number.isFinite(p.fair_decimal_odds)
      ? formatAmericanOdds(decimalToAmerican(p.fair_decimal_odds))
      : '—'
  const wagerLabel = p.stake_cents != null ? formatUsdFromCents(p.stake_cents) : '—'
  const payoutLabel = p.payout_cents != null ? formatUsdFromCents(p.payout_cents) : '—'
  return (
    <div className="page">
      <section className="card">
        <div className="parlay-detail__head">
          <h1 className="page-title">Parlay #{p.id}</h1>
          <p className="parlay-detail__odds">{fairAmerican}</p>
        </div>
        <p className="page-lede">
          <Link to="/" className="inline-link">
            ← Home
          </Link>
        </p>

        {groups.map((g) => (
          <div key={g.game}>
            <h2 className="parlay-detail__legs-heading">
              <span>{g.game}</span>
              {g.scoreLabel ? (
                <span className="parlay-detail__game-score-wrap">
                  {g.scoreIsFinal ? <span className="parlay-detail__game-final">FINAL</span> : null}
                  <span className="parlay-detail__game-score">{g.scoreLabel}</span>
                </span>
              ) : null}
            </h2>
            <ul className="parlay-leg-list">
              {g.rows.map((row) => (
                <li key={row.key} className="parlay-leg-row">
                  <LegOutcomeIcon outcome={row.outcome} />
                  {row.playerImageUrl ? (
                    <span className="parlay-leg-row__player-image-wrap">
                      <img src={row.playerImageUrl} alt="" className="parlay-leg-row__player-image" loading="lazy" />
                      {row.playerTeamLogoUrl ? (
                        <img src={row.playerTeamLogoUrl} alt="" className="parlay-leg-row__player-team-badge" loading="lazy" />
                      ) : null}
                    </span>
                  ) : null}
                  <div className="parlay-leg-row__body">
                    <span className="parlay-leg-row__text">{row.text}</span>
                    {row.kind === 'player' ? (
                      <div className="parlay-leg-progress">
                        <div className="parlay-leg-progress__meta">
                          <span>
                            {row.statValue != null ? row.statValue.toFixed(0) : '—'} / {row.line != null ? formatHalfPointLine(row.line) : '—'}
                          </span>
                          <span>{row.direction}</span>
                        </div>
                        {(() => {
                          const progress = playerProgressValue(row.statValue, row.line)
                          return (
                            <div className="parlay-leg-progress__track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
                              <span className="parlay-leg-progress__threshold" />
                              <span className="parlay-leg-progress__fill" style={{ width: `${progress}%` }} />
                            </div>
                          )
                        })()}
                      </div>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div className="parlay-detail__footer">
          <span>Wager: {wagerLabel}</span>
          <span>Payout: {payoutLabel}</span>
        </div>
      </section>
    </div>
  )
}

export function ParlayDetailPage() {
  const { parlayId } = useParams<{ parlayId: string }>()
  const id = parseId(parlayId)

  if (!id) {
    return <InvalidParlayId />
  }

  return <ParlayDetailLoaded key={parlayId} id={id} />
}
