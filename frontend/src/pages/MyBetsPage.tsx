import { startTransition, useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { ApiError } from '../api/client'
import { getWagerDetail, listWagers } from '../api/endpoints'
import type {
  ParlayGameLegRead,
  ParlayLegOutcome,
  ParlayLegRead,
  WagerDetailResponse,
  WagerRead,
  WagerStatus,
} from '../api/types'
import { formatHalfPointLine } from '../components/browse/format'
import { formatGameDate, formatTipOrGameStatusLabel } from '../components/browse/format'
import { useWallet } from '../context/WalletContext'
import { formatUsdFromCents } from '../lib/formatMoney'
import { decimalToAmerican, formatAmericanOdds } from '../utils/parlayOdds'

function statusLabel(s: WagerStatus): string {
  switch (s) {
    case 'open':
      return 'Open'
    case 'won':
      return 'Won'
    case 'lost':
      return 'Lost'
    case 'void':
      return 'Void'
    case 'cancelled':
      return 'Cancelled'
    default:
      return s
  }
}

function formatPlacedAt(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

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
      <svg className="my-bets__leg-status my-bets__leg-status--hit" width={22} height={22} viewBox="0 0 24 24" role="img" aria-label={label}>
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
      <svg className="my-bets__leg-status my-bets__leg-status--miss" width={22} height={22} viewBox="0 0 24 24" role="img" aria-label={label}>
        {circle}
        <path d="M8 8 16 16M16 8 8 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    )
  }
  return (
    <svg className="my-bets__leg-status my-bets__leg-status--neutral" width={22} height={22} viewBox="0 0 24 24" role="img" aria-label={label}>
      {circle}
      <line x1="7.5" y1="12" x2="16.5" y2="12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

function formatPlayerLeg(leg: ParlayLegRead): string {
  const name = leg.player_full_name?.trim() || `Player #${leg.player_id}`
  const line = formatHalfPointLine(leg.line)
  return `${name} · ${leg.stat_type} ${leg.direction} ${line}`
}

function formatGameLeg(leg: ParlayGameLegRead): string {
  const game = leg.game_label || `Game #${leg.game_id}`
  const homeTeam = leg.home_team_name || 'Home'
  const awayTeam = leg.away_team_name || 'Away'
  const odds = `${leg.odds_american >= 0 ? '+' : ''}${leg.odds_american}`
  if (leg.market_type === 'moneyline') {
    const team = leg.selection === 'home' ? homeTeam : awayTeam
    return `${team} MONEYLINE (${odds})`
  }
  if (leg.market_type === 'spread') {
    const team = leg.selection === 'home' ? homeTeam : awayTeam
    const line = leg.line ?? 0
    return `${team} SPREAD ${line >= 0 ? '+' : ''}${line.toFixed(1)} (${odds})`
  }
  const side = leg.selection === 'over' ? 'OVER' : 'UNDER'
  return `${game} TOTAL ${side} ${(leg.line ?? 0).toFixed(1)} (${odds})`
}

type GroupedRow = { key: string; text: string; outcome?: ParlayLegOutcome | null }

type GroupedGame = { game: string; meta: string; rows: GroupedRow[] }

function groupedLegs(detail: WagerDetailResponse): GroupedGame[] {
  const map = new Map<string, GroupedRow[]>()
  const metaByGame = new Map<string, string>()
  const order: string[] = []
  const push = (
    game: string,
    row: GroupedRow,
    gameDate: string | null | undefined,
    gameTimeUtc: string | null | undefined,
    gameStatus: string | null | undefined,
  ) => {
    if (!map.has(game)) {
      map.set(game, [])
      order.push(game)
      if (gameDate) {
        const tail = formatTipOrGameStatusLabel(gameTimeUtc, gameStatus)
        metaByGame.set(game, tail ? `${formatGameDate(gameDate)} · ${tail}` : formatGameDate(gameDate))
      } else {
        metaByGame.set(game, '')
      }
    }
    map.get(game)!.push(row)
  }
  for (const leg of [...detail.parlay.legs].sort((a, b) => a.sort_order - b.sort_order)) {
    push(leg.game_label || 'No specific game', {
      key: `player-${leg.id}`,
      text: formatPlayerLeg(leg),
      outcome: leg.outcome,
    }, leg.game_date, leg.game_time_utc, leg.game_status)
  }
  for (const leg of [...(detail.parlay.game_legs ?? [])].sort((a, b) => a.sort_order - b.sort_order)) {
    push(leg.game_label || `Game #${leg.game_id}`, {
      key: `game-${leg.id}`,
      text: formatGameLeg(leg),
      outcome: leg.outcome,
    }, leg.game_date, leg.game_time_utc, leg.game_status)
  }
  return order.map((game) => ({ game, meta: metaByGame.get(game) ?? '', rows: map.get(game)! }))
}

function parlayModeLabel(detail: WagerDetailResponse | undefined): string | null {
  const p = detail?.parlay
  if (!p) return null
  const parts: string[] = []
  if (p.wager_on_hit === false) parts.push('Anti-parlay')
  if (p.mode === 'x_of_y' && p.k_required != null) parts.push(`${p.k_required}+ legs required`)
  return parts.length > 0 ? parts.join(' · ') : null
}

export function MyBetsPage() {
  const { pathname } = useLocation()
  const tab: 'open' | 'settled' = pathname.includes('/bets/settled') ? 'settled' : 'open'
  const { accountId } = useWallet()
  const [rows, setRows] = useState<WagerRead[] | null>(null)
  const [detailsByWager, setDetailsByWager] = useState<Record<number, WagerDetailResponse>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (accountId == null) {
      setRows(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await listWagers(accountId, { limit: 200 })
      setRows(data)
      const detailPairs = await Promise.all(
        data.map(async (w) => {
          try {
            const detail = await getWagerDetail(accountId, w.id)
            return [w.id, detail] as const
          } catch {
            return null
          }
        }),
      )
      const nextDetails: Record<number, WagerDetailResponse> = {}
      for (const pair of detailPairs) {
        if (!pair) continue
        nextDetails[pair[0]] = pair[1]
      }
      setDetailsByWager(nextDetails)
    } catch (e) {
      if (e instanceof ApiError) setError(e.message)
      else setError(e instanceof Error ? e.message : 'Failed to load bets.')
      setRows(null)
    } finally {
      setLoading(false)
    }
  }, [accountId])

  useEffect(() => {
    startTransition(() => {
      void load()
    })
  }, [load])

  const filtered = useMemo(() => {
    if (!rows) return []
    if (tab === 'open') return rows.filter((w) => w.status === 'open')
    return rows.filter((w) => w.status !== 'open')
  }, [rows, tab])

  if (accountId == null) {
    return (
      <section className="my-bets card">
        <h1 className="my-bets__title">My Bets</h1>
        <p className="muted">Log in or continue as guest to place bets and see them here.</p>
      </section>
    )
  }

  return (
    <section className="my-bets card">
      <h1 className="my-bets__title">My Bets</h1>

      <nav className="my-bets__subnav" aria-label="Bet filter">
        <NavLink
          to="/bets/open"
          className={({ isActive }) => `my-bets__subtab${isActive ? ' my-bets__subtab--active' : ''}`}
        >
          Open
        </NavLink>
        <NavLink
          to="/bets/settled"
          className={({ isActive }) => `my-bets__subtab${isActive ? ' my-bets__subtab--active' : ''}`}
        >
          Settled
        </NavLink>
      </nav>

      {loading && (
        <p className="my-bets__status muted" aria-live="polite">
          Loading bets…
        </p>
      )}
      {error && (
        <div className="my-bets__err">
          <p>{error}</p>
          <button type="button" className="btn-text" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}
      {!loading && !error && filtered.length === 0 && (
        <p className="my-bets__empty muted">
          {tab === 'open'
            ? 'No open bets. Place one from Home or a game page using the slip.'
            : 'No settled bets yet.'}
        </p>
      )}
      {filtered.length > 0 && (
        <div className="my-bets__cards">
          {filtered.map((w) => {
            const detail = detailsByWager[w.id]
            const groups = detail ? groupedLegs(detail) : []
            const parlay = detail?.parlay
            const modeLabel = parlayModeLabel(detail)
            const wagerLegCount = (parlay?.legs.length ?? 0) + (parlay?.game_legs?.length ?? 0)
            const fairAmerican =
              parlay?.fair_decimal_odds != null && Number.isFinite(parlay.fair_decimal_odds)
                ? formatAmericanOdds(decimalToAmerican(parlay.fair_decimal_odds))
                : '—'
            const payout =
              parlay?.payout_cents != null
                ? formatUsdFromCents(parlay.payout_cents)
                : w.status === 'open'
                  ? formatUsdFromCents(w.potential_return_cents)
                  : '$0.00'
            return (
              <details key={w.id} className="my-bets__card" open>
                <summary className="my-bets__card-head">
                  <div className="my-bets__card-left">
                    <span className="my-bets__card-id">{wagerLegCount} leg parlay</span>
                    {modeLabel && <span className="my-bets__card-mode">{modeLabel}</span>}
                    <span className="my-bets__card-placed muted">{formatPlacedAt(w.created_at)}</span>
                  </div>
                  <div className="my-bets__card-right">
                    <span className="my-bets__card-odds">{fairAmerican}</span>
                    <span className={`my-bets__pill my-bets__pill--${w.status}`}>{statusLabel(w.status)}</span>
                  </div>
                </summary>
                <div className="my-bets__card-body">
                  {detail ? (
                    <>
                      {groups.map((g) => (
                        <div key={`${w.id}-${g.game}`}>
                          <h3 className="my-bets__game-head">
                            <span>{g.game}</span>
                            <span className="my-bets__game-head-meta">{g.meta}</span>
                          </h3>
                          <ul className="my-bets__leg-list">
                            {g.rows.map((row) => (
                              <li key={row.key} className="my-bets__leg-row">
                                <LegOutcomeIcon outcome={row.outcome} />
                                <span>{row.text}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))}
                      <div className="my-bets__totals">
                        <span>Wager: {formatUsdFromCents(parlay?.stake_cents ?? w.stake_cents)}</span>
                        <span>Payout: {payout}</span>
                      </div>
                    </>
                  ) : (
                    <p className="muted">Loading bet details…</p>
                  )}
                </div>
              </details>
            )
          })}
        </div>
      )}
    </section>
  )
}
