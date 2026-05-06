import type { ISODateString } from '../../api/types'

export function formatGameDate(d: ISODateString): string {
  const [y, m, day] = d.split('-').map(Number)
  if (!y || !m || !day) return d
  const date = new Date(y, m - 1, day)
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

/** Tip-off time in the user's locale from API UTC ISO (`game_time_utc`). */
export function formatGameTimeLocal(isoUtc: string | null | undefined): string | null {
  if (isoUtc == null || !String(isoUtc).trim()) return null
  const d = new Date(isoUtc)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

/**
 * Same idea as the home upcoming row after the calendar date: use synced UTC tip when present,
 * otherwise fall back to `game.status` from the NBA scoreboard (often displays tip time).
 */
export function formatTipOrGameStatusLabel(
  gameTimeUtc: string | null | undefined,
  gameStatus: string | null | undefined,
): string | null {
  const tip = formatGameTimeLocal(gameTimeUtc)
  if (tip) return tip
  const st = gameStatus?.trim()
  return st ? st : null
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
