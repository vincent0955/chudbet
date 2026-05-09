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
