import type { ISODateString } from '../../api/types'

export function formatGameDate(d: ISODateString): string {
  const [y, m, day] = d.split('-').map(Number)
  if (!y || !m || !day) return d
  const date = new Date(y, m - 1, day)
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function formatStat(n: number, maxFractionDigits = 1): string {
  if (Number.isInteger(n)) return String(n)
  return n.toFixed(maxFractionDigits)
}

/** Matches server: nearest line that always ends in *.5 (never *.0). */
export function formatHalfPointLine(n: number): string {
  const line = Math.round(n - 0.5) + 0.5
  return line.toFixed(1)
}
