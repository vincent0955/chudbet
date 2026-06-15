/**
 * Pre-game wager gate aligned with backend ``game_wager_gate``.
 *
 * NBA games use quarter/clock heuristics; MLB games use status classification
 * (``PRE_GAME`` open; ``LIVE``/``FINAL`` closed).
 */

export type MlbGameStatusClass = 'pre_game' | 'live' | 'final'

const MLB_FINAL = new Set(['final', 'game over'])
const MLB_PRE_GAME = new Set(['scheduled', 'pre-game', 'pregame', 'warmup', 'preview'])

function normalizeStatus(raw: string | null | undefined): string {
  return String(raw ?? '')
    .trim()
    .toLowerCase()
}

/** Classify an MLB ``Game.status`` string (Req 4.2 / 12.4). */
export function classifyMlbStatus(statusRaw: string | null | undefined): MlbGameStatusClass {
  const detailed = normalizeStatus(statusRaw)
  if (MLB_FINAL.has(detailed)) return 'final'
  if (MLB_PRE_GAME.has(detailed)) return 'pre_game'
  if (detailed === '') return 'pre_game'
  return 'live'
}

export function mlbStatusIndicatesLiveOrFinished(statusRaw: string | null | undefined): boolean {
  const cls = classifyMlbStatus(statusRaw)
  return cls === 'live' || cls === 'final'
}

/**
 * Align with backend ``game_wager_gate.status_indicates_live_or_finished``:
 * wagering is only for games that have not gone live (no quarter / OT / halftime / final).
 */
export function statusIndicatesLiveOrFinished(statusRaw: string | null | undefined): boolean {
  const s = String(statusRaw ?? '')
    .trim()
    .toUpperCase()
  if (!s) return false
  if (s.includes('FINAL') || s.includes('POSTPONED') || s.includes('CANCELLED')) return true
  if (s.includes('HALFTIME') || s.includes('HALF') || s.includes('END OF')) return true
  if (/\b(?:1ST|2ND|3RD|4TH)\s+QTR\b/.test(s) || /\bQ\s*[1-4]\b/.test(s)) return true
  if (/\bOT\b/.test(s)) return true
  if (/^\d{1,2}:\d{2}\b/.test(s) && !s.includes('AM') && !s.includes('PM') && !s.includes('ET')) return true
  return false
}

export function gameAcceptsPreGameWagers(game: {
  sport?: string | null
  status?: string | null
}): boolean {
  if (game.sport === 'MLB') {
    return classifyMlbStatus(game.status) === 'pre_game'
  }
  return !statusIndicatesLiveOrFinished(game.status)
}
