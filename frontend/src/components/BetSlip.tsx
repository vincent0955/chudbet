import { useEffect, useId, useState } from 'react'
import { useBetSlip } from '../context/BetSlipContext'

function usePrefersMobileSlip(): boolean {
  const [mobile, setMobile] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 899px)')
    const apply = () => setMobile(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])
  return mobile
}

function initialExpandedForViewport(): boolean {
  if (typeof window === 'undefined') return true
  return !window.matchMedia('(max-width: 899px)').matches
}

export function BetSlip() {
  const mobile = usePrefersMobileSlip()
  const [expanded, setExpanded] = useState(initialExpandedForViewport)
  const panelId = useId()
  const { legs, removeLeg, clearLegs } = useBetSlip()

  const showExpanded = !mobile || expanded
  const count = legs.length

  const row = (
    <>
      <span className="bet-slip__title">Bet slip</span>
      <span className="bet-slip__meta">
        {count} leg{count === 1 ? '' : 's'}
      </span>
      {mobile && (
        <span className="bet-slip__chevron" aria-hidden>
          {showExpanded ? '▾' : '▴'}
        </span>
      )}
    </>
  )

  return (
    <div className={`bet-slip ${showExpanded ? 'bet-slip--expanded' : 'bet-slip--collapsed'}`}>
      <div className="bet-slip__chrome">
        {mobile ? (
          <button
            type="button"
            className="bet-slip__toggle"
            aria-expanded={showExpanded}
            aria-controls={panelId}
            onClick={() => setExpanded((e) => !e)}
          >
            {row}
          </button>
        ) : (
          <div className="bet-slip__head">{row}</div>
        )}
      </div>

      <div id={panelId} className="bet-slip__body" hidden={!showExpanded}>
        {count === 0 ? (
          <div className="bet-slip__empty">
            <p className="bet-slip__empty-title">Your slip is empty</p>
            <p className="bet-slip__empty-text">
              Add props from a game page (points / rebounds / assists) or the Players browse tab. Choose standard,{' '}
              <strong>X of Y</strong>, or <strong>anti-parlay</strong> modes when you submit the ticket in the next
              phase.
            </p>
          </div>
        ) : (
          <div className="bet-slip__legs">
            <div className="bet-slip__legs-header">
              <span className="bet-slip__legs-label">Legs</span>
              <button type="button" className="btn-text bet-slip__clear" onClick={clearLegs}>
                Clear all
              </button>
            </div>
            <ul className="bet-slip__leg-list">
              {legs.map((row) => (
                <li key={row.id} className="bet-slip__leg">
                  <div className="bet-slip__leg-main">
                    <p className="bet-slip__leg-primary">{row.primary}</p>
                    {row.secondary && <p className="bet-slip__leg-secondary muted">{row.secondary}</p>}
                  </div>
                  <button
                    type="button"
                    className="bet-slip__leg-remove"
                    onClick={() => removeLeg(row.id)}
                    aria-label={`Remove leg: ${row.primary}`}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
