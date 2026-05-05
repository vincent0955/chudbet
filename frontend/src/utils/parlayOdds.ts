/** Parse odds like "-114", "+150", or "220" → +220. Returns null if not a usable price. */
export function parseAmericanOddsString(raw: string): number | null {
  const s = raw.trim().replace(/\s+/g, '')
  if (!s) return null
  if (/^\+/.test(s)) {
    const n = Number(s.slice(1))
    return Number.isFinite(n) && n > 0 ? n : null
  }
  if (/^-/.test(s)) {
    const n = Number(s.slice(1))
    return Number.isFinite(n) && n !== 0 ? -Math.abs(n) : null
  }
  const n = Number(s)
  return Number.isFinite(n) && n > 0 ? n : null
}

export function americanToDecimal(american: number): number {
  if (american === 0) return NaN
  if (american > 0) return 1 + american / 100
  return 1 + 100 / Math.abs(american)
}

/** Converts combined decimal payout odds (stake multiplier) → American (rounded integer). */
export function decimalToAmerican(decimalOdds: number): number {
  if (!Number.isFinite(decimalOdds) || decimalOdds <= 1) return NaN
  if (decimalOdds >= 2) return Math.round((decimalOdds - 1) * 100)
  return Math.round(-100 / (decimalOdds - 1))
}

export function formatAmericanOdds(american: number): string {
  const r = Math.round(american)
  if (r > 0) return `+${r}`
  return String(r)
}

/** Independent-leg parlay: multiply payout decimals and map to rounded American odds. */
export function combineAmericanParlay(
  americanOdds: readonly number[],
): { payoutDecimal: number; american: number } | null {
  let d = 1
  for (const a of americanOdds) {
    const next = americanToDecimal(a)
    if (!Number.isFinite(next)) return null
    d *= next
  }
  const american = decimalToAmerican(d)
  if (!Number.isFinite(american)) return null
  return { payoutDecimal: d, american }
}

/**
 * Independent-leg parlay: multiply decimal prices, convert back to American (rounded integer).
 */
export function combineAmericanParlayPrices(americanOdds: readonly number[]): number {
  const r = combineAmericanParlay(americanOdds)
  return r?.american ?? NaN
}

/** Same rounding as backend `potential_return_cents`: `round(stake_cents × payout_decimal)`. */
export function parlayPotentialReturnCents(stakeCents: number, payoutDecimal: number): number {
  if (!Number.isFinite(stakeCents) || stakeCents <= 0 || !Number.isFinite(payoutDecimal)) return NaN
  return Math.round(stakeCents * payoutDecimal)
}
