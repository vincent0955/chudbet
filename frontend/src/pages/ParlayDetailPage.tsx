import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, getParlay } from '../api'
import type { ParlayRead } from '../api/types'

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
