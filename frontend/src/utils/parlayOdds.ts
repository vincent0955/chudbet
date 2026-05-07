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

/** Fair implied probability from American odds (no-vig simplification). */
export function impliedProbFromAmerican(american: number): number {
  if (!Number.isFinite(american) || american === 0) return NaN
  if (american > 0) return 100 / (american + 100)
  return Math.abs(american) / (Math.abs(american) + 100)
}

function fairDecimalFromProbability(p: number): number {
  if (!Number.isFinite(p) || p <= 0 || p >= 1) return NaN
  return 1 / p
}

function poissonBinomialHitDistribution(probs: readonly number[]): number[] | null {
  const n = probs.length
  if (n < 1) return null
  const dp = new Array<number>(n + 1).fill(0)
  dp[0] = 1
  for (const p of probs) {
    if (!Number.isFinite(p) || p < 0 || p > 1) return null
    for (let h = n; h >= 0; h -= 1) {
      const miss = dp[h] * (1 - p)
      const hit = h > 0 ? dp[h - 1] * p : 0
      dp[h] = miss + hit
    }
  }
  return dp
}

export type PriceParlayByModeArgs = {
  mode: 'standard' | 'x_of_y'
  kRequired?: number | null
  wagerOnHit: boolean
  /** House margin rate (e.g. 0.14 for 14%). */
  marginRate?: number
}

const DEFAULT_MARGIN_RATE = 0.14

function overroundFromMarginRate(marginRate: number): number {
  const m = Number.isFinite(marginRate) ? Math.max(0, marginRate) : DEFAULT_MARGIN_RATE
  return 1 + m / (2 + m)
}

function applyTwoWayMarginToSelectedProbability(pFair: number, marginRate: number): number {
  if (!Number.isFinite(pFair) || pFair <= 0 || pFair >= 1) return NaN
  const overround = overroundFromMarginRate(marginRate)
  return Math.min(0.999, Math.max(0.001, pFair * overround))
}

/**
 * Prices a parlay from individual leg American odds using hit-count distribution.
 * Returns payout odds for selected mode and side with margin correction applied.
 */
export function priceParlayByMode(
  americanOdds: readonly number[],
  args: PriceParlayByModeArgs,
): { payoutDecimal: number; american: number; pTicket: number } | null {
  if (americanOdds.length < 1) return null
  const marginRate = args.marginRate ?? DEFAULT_MARGIN_RATE
  const overround = overroundFromMarginRate(marginRate)
  const probs = americanOdds
    .map((a) => impliedProbFromAmerican(a))
    .map((pBook) => (Number.isFinite(pBook) ? pBook / overround : NaN))
  if (probs.some((p) => !Number.isFinite(p) || p <= 0 || p >= 1)) return null
  const dist = poissonBinomialHitDistribution(probs)
  if (!dist) return null

  const n = americanOdds.length
  let pHitCondition: number
  if (args.mode === 'standard') {
    pHitCondition = dist[n] ?? NaN
  } else {
    const k = args.kRequired
    if (k == null || !Number.isInteger(k) || k < 1 || k > n) return null
    let acc = 0
    for (let h = k; h <= n; h += 1) acc += dist[h] ?? 0
    pHitCondition = acc
  }
  if (!Number.isFinite(pHitCondition)) return null

  const pTicketFair = args.wagerOnHit ? pHitCondition : 1 - pHitCondition
  const pTicket = applyTwoWayMarginToSelectedProbability(
    pTicketFair,
    marginRate,
  )
  const payoutDecimal = fairDecimalFromProbability(pTicket)
  if (!Number.isFinite(payoutDecimal)) return null
  const american = decimalToAmerican(payoutDecimal)
  if (!Number.isFinite(american)) return null
  return { payoutDecimal, american, pTicket }
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
