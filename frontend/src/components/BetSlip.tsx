import { useEffect, useId, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { placeWager } from '../api/endpoints'
import { useBetSlip } from '../context/BetSlipContext'
import { useWallet } from '../context/WalletContext'
import { formatUsdFromCents } from '../lib/formatMoney'
import {
  combineAmericanParlay,
  formatAmericanOdds,
  parlayPotentialReturnCents,
} from '../utils/parlayOdds'

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
  const navigate = useNavigate()
  const mobile = usePrefersMobileSlip()
  const [expanded, setExpanded] = useState(initialExpandedForViewport)
  const panelId = useId()
  const { legs, removeLeg, clearLegs } = useBetSlip()
  const { accountId, balanceCents, loading: walletLoading, refresh } = useWallet()
  const [stakeStr, setStakeStr] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitErr, setSubmitErr] = useState<string | null>(null)

  const showExpanded = !mobile || expanded
  const count = legs.length

  const combinedParlay = useMemo(() => {
    if (legs.length === 0) return null
    const prices = legs.map((r) => r.americanOdds)
    if (prices.some((p) => p == null)) return { kind: 'incomplete' as const }
    const packed = combineAmericanParlay(prices as number[])
    if (!packed) return { kind: 'incomplete' as const }
    return { kind: 'priced' as const, american: packed.american, payoutDecimal: packed.payoutDecimal }
  }, [legs])

  const stakeCentsParsed = useMemo(() => {
    const t = stakeStr.trim()
    if (!t) return null
    const n = Number.parseFloat(t.replace(/,/g, ''))
    if (!Number.isFinite(n) || n <= 0) return null
    return Math.round(n * 100)
  }, [stakeStr])

  const payoff = useMemo(() => {
    if (combinedParlay?.kind !== 'priced' || stakeCentsParsed == null) {
      return { kind: 'none' as const }
    }
    const returnCents = parlayPotentialReturnCents(stakeCentsParsed, combinedParlay.payoutDecimal)
    if (!Number.isFinite(returnCents)) return { kind: 'none' as const }
    const profitCents = returnCents - stakeCentsParsed
    return { kind: 'ok' as const, returnCents, profitCents, stakeCents: stakeCentsParsed }
  }, [combinedParlay, stakeCentsParsed])

  const priced = combinedParlay?.kind === 'priced'

  const overBalance = Boolean(
    balanceCents != null && stakeCentsParsed != null && stakeCentsParsed > balanceCents,
  )

  const canSubmit = Boolean(
    accountId != null &&
      priced &&
      stakeCentsParsed != null &&
      stakeCentsParsed >= 1 &&
      !overBalance &&
      !walletLoading &&
      !submitting,
  )

  const submitDisabledReason = useMemo(() => {
    if (count === 0) return ''
    if (submitting || walletLoading) return ''
    if (accountId == null) return 'Configure a wallet id (VITE_ACCOUNT_ID).'
    if (!priced) return 'Every leg needs a price before you can submit.'
    if (stakeCentsParsed == null || stakeCentsParsed < 1) return 'Enter a valid wager.'
    if (overBalance) return 'Wager is larger than your wallet balance.'
    return ''
  }, [
    accountId,
    count,
    overBalance,
    priced,
    stakeCentsParsed,
    submitting,
    walletLoading,
  ])

  const handlePlaceBet = async () => {
    if (!canSubmit || accountId == null || combinedParlay?.kind !== 'priced' || stakeCentsParsed == null) return
    setSubmitErr(null)
    setSubmitting(true)
    try {
      await placeWager(accountId, {
        stake_cents: stakeCentsParsed,
        offered_decimal_odds: combinedParlay.payoutDecimal,
        idempotency_key:
          typeof crypto !== 'undefined' && crypto.randomUUID
            ? crypto.randomUUID()
            : `bet-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        parlay: {
          mode: 'standard',
          wager_on_hit: true,
          legs: legs.map((r) => r.leg),
        },
      })
      await refresh()
      clearLegs()
      setStakeStr('')
      navigate('/bets/open')
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) setSubmitErr('Insufficient wallet balance.')
        else setSubmitErr(e.message)
      } else {
        setSubmitErr(e instanceof Error ? e.message : 'Could not place bet.')
      }
    } finally {
      setSubmitting(false)
    }
  }

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
              Add props from a game page (points / rebounds / assists) or the Players browse tab, set a wager, then
              place your bet. Open tickets live under <strong>My bets</strong>.
            </p>
          </div>
        ) : (
          <div className="bet-slip__legs">
            <div className="bet-slip__legs-header">
              <span className="bet-slip__legs-label">Legs</span>
              <button
                type="button"
                className="btn-text bet-slip__clear"
                onClick={() => {
                  clearLegs()
                  setStakeStr('')
                }}
              >
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
            <div className="bet-slip__stake">
              <label className="bet-slip__stake-field" htmlFor={`${panelId}-stake`}>
                <span className="bet-slip__stake-label">Wager</span>
                <span className="bet-slip__stake-input-wrap">
                  <span className="bet-slip__stake-dollar" aria-hidden>
                    $
                  </span>
                  <input
                    id={`${panelId}-stake`}
                    className="bet-slip__stake-input"
                    type="number"
                    inputMode="decimal"
                    min={0}
                    step="0.01"
                    placeholder="0.00"
                    autoComplete="off"
                    value={stakeStr}
                    onChange={(e) => setStakeStr(e.target.value)}
                  />
                </span>
              </label>
            </div>
            {combinedParlay && (
              <div className="bet-slip__combined">
                <div className="bet-slip__combined-row">
                  <span className="bet-slip__combined-label">Combined odds</span>
                  <span className="bet-slip__combined-value" aria-live="polite">
                    {combinedParlay.kind === 'priced'
                      ? formatAmericanOdds(combinedParlay.american)
                      : '—'}
                  </span>
                </div>
                {combinedParlay.kind === 'priced' &&
                  stakeStr.trim().length > 0 &&
                  stakeCentsParsed == null && (
                    <p className="bet-slip__combined-hint muted">Enter a valid wager amount.</p>
                  )}
                {combinedParlay.kind === 'incomplete' && (
                  <p className="bet-slip__combined-hint muted">
                    Payoff appears when every leg has American odds (game props, or optional odds on Add prop).
                  </p>
                )}
                {payoff.kind === 'ok' && (
                  <div className="bet-slip__payoff" aria-live="polite">
                    <div className="bet-slip__payoff-row">
                      <span className="bet-slip__payoff-label">Potential payout</span>
                      <span className="bet-slip__payoff-value">{formatUsdFromCents(payoff.returnCents)}</span>
                    </div>
                    <p className="bet-slip__payoff-sub muted">
                      To win{' '}
                      <span className="bet-slip__payoff-profit">{formatUsdFromCents(payoff.profitCents)}</span>{' '}
                      (risk {formatUsdFromCents(payoff.stakeCents)})
                    </p>
                  </div>
                )}
              </div>
            )}
            <div className="bet-slip__submit">
              {submitErr && <p className="bet-slip__submit-err">{submitErr}</p>}
              {!canSubmit && submitDisabledReason && (
                <p className="bet-slip__submit-hint muted">{submitDisabledReason}</p>
              )}
              <button
                type="button"
                className="btn-primary bet-slip__submit-btn"
                disabled={!canSubmit}
                onClick={() => void handlePlaceBet()}
              >
                {submitting ? 'Placing…' : 'Place bet'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
