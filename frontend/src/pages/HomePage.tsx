import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getHealth } from '../api'

export function HomePage() {
  const [apiStatus, setApiStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [apiMessage, setApiMessage] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const h = await getHealth()
        if (!cancelled) {
          setApiStatus(h.status === 'ok' ? 'ok' : 'error')
          setApiMessage(h.status === 'ok' ? 'API reachable' : `Unexpected: ${h.status}`)
        }
      } catch (e) {
        if (!cancelled) {
          setApiStatus('error')
          setApiMessage(e instanceof ApiError ? e.message : 'Could not reach API')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="page">
      <section className="card">
        <h1 className="page-title">Chudbet</h1>
        <p className="page-lede">
          Phase 0 foundation: routing, API client, and design tokens. Browse and parlay builder UI come next.
        </p>
        <dl className="kv">
          <div className="kv__row">
            <dt>API</dt>
            <dd>
              {apiStatus === 'loading' && <span className="muted">Checking…</span>}
              {apiStatus === 'ok' && <span className="status-ok">{apiMessage}</span>}
              {apiStatus === 'error' && <span className="status-err">{apiMessage}</span>}
            </dd>
          </div>
        </dl>
        <p className="hint">
          Example parlay URL (after you create one):{' '}
          <Link to="/parlays/1" className="inline-link">
            /parlays/1
          </Link>
        </p>
      </section>
    </div>
  )
}
