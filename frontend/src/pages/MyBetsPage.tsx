import { startTransition, useCallback, useEffect, useMemo, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { ApiError } from '../api/client'
import { listWagers } from '../api/endpoints'
import type { WagerRead, WagerStatus } from '../api/types'
import { useWallet } from '../context/WalletContext'
import { formatUsdFromCents } from '../lib/formatMoney'

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

export function MyBetsPage() {
  const { pathname } = useLocation()
  const tab: 'open' | 'settled' = pathname.includes('/bets/settled') ? 'settled' : 'open'
  const { accountId } = useWallet()
  const [rows, setRows] = useState<WagerRead[] | null>(null)
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
        <h1 className="my-bets__title">My bets</h1>
        <p className="muted">Set VITE_ACCOUNT_ID in env to use a wallet and see your bets here.</p>
      </section>
    )
  }

  return (
    <section className="my-bets card">
      <h1 className="my-bets__title">My bets</h1>

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
        <div className="my-bets__table-wrap">
          <table className="my-bets__table">
            <thead>
              <tr>
                <th scope="col">Placed</th>
                <th scope="col">Parlay</th>
                <th scope="col" className="my-bets__num">
                  Risk
                </th>
                <th scope="col" className="my-bets__num">
                  Odds (dec.)
                </th>
                <th scope="col" className="my-bets__num">
                  Pays
                </th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((w) => (
                <tr key={w.id}>
                  <td className="my-bets__cell-muted">{formatPlacedAt(w.created_at)}</td>
                  <td>
                    <Link to={`/parlays/${w.parlay_id}`} className="my-bets__link">
                      #{w.parlay_id}
                    </Link>
                  </td>
                  <td className="my-bets__num">{formatUsdFromCents(w.stake_cents)}</td>
                  <td className="my-bets__num">{w.offered_decimal_odds.toFixed(3)}×</td>
                  <td className="my-bets__num">{formatUsdFromCents(w.potential_return_cents)}</td>
                  <td>
                    <span className={`my-bets__pill my-bets__pill--${w.status}`}>{statusLabel(w.status)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
