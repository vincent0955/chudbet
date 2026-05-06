import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, getParlay } from '../api'
import type { ParlayLegOutcome, ParlayLegRead, ParlayRead } from '../api/types'
import { formatHalfPointLine } from '../components/browse/format'

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
  return (
    <div className="page">
      <section className="card">
        <h1 className="page-title">Parlay #{p.id}</h1>
        <p className="page-lede">
          <Link to="/" className="inline-link">
            ← Home
          </Link>
        </p>
        <dl className="kv">
          <div className="kv__row">
            <dt>Mode</dt>
            <dd>{p.mode}</dd>
          </div>
          {p.k_required != null && (
            <div className="kv__row">
              <dt>k of y</dt>
              <dd>{p.k_required}</dd>
            </div>
          )}
          <div className="kv__row">
            <dt>Legs</dt>
            <dd>{p.total_legs}</dd>
          </div>
          <div className="kv__row">
            <dt>P(hit)</dt>
            <dd>{p.p_hit != null ? p.p_hit.toFixed(4) : '—'}</dd>
          </div>
          <div className="kv__row">
            <dt>Fair decimal</dt>
            <dd>{p.fair_decimal_odds != null ? p.fair_decimal_odds.toFixed(3) : '—'}</dd>
          </div>
        </dl>

        <h2 className="parlay-detail__legs-heading">Parlay legs</h2>
        <ul className="parlay-leg-list">
          {[...p.legs]
            .sort((a, b) => a.sort_order - b.sort_order)
            .map((leg) => (
              <li key={leg.id} className="parlay-leg-row">
                <LegOutcomeIcon outcome={leg.outcome} />
                <span className="parlay-leg-row__text">{formatLegSummary(leg)}</span>
              </li>
            ))}
        </ul>
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
