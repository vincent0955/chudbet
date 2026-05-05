import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { LegIn } from '../api/types'

export type SlipLegRow = {
  id: string
  leg: LegIn
  /** Short label, e.g. player · stat · O/U line */
  primary: string
  /** Optional context, e.g. game date or matchup */
  secondary?: string
  /** Priced American odds for this selection, when known (e.g. from game props). */
  americanOdds: number | null
}

type BetSlipContextValue = {
  legs: SlipLegRow[]
  addLeg: (
    leg: LegIn,
    display: { primary: string; secondary?: string },
    americanOdds?: number | null,
  ) => boolean
  hasLeg: (leg: LegIn) => boolean
  removeLegByLeg: (leg: LegIn) => void
  removeLeg: (id: string) => void
  clearLegs: () => void
}

const BetSlipContext = createContext<BetSlipContextValue | null>(null)

function newRowId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function BetSlipProvider({ children }: { children: ReactNode }) {
  const [legs, setLegs] = useState<SlipLegRow[]>([])

  const sameLine = useCallback((a: number, b: number) => Math.abs(a - b) < 1e-9, [])

  const samePropKey = useCallback(
    (a: LegIn, b: LegIn): boolean => {
      return (
        a.player_id === b.player_id &&
        a.game_id === b.game_id &&
        a.stat_type === b.stat_type &&
        sameLine(a.line, b.line)
      )
    },
    [sameLine],
  )

  const sameLeg = useCallback(
    (a: LegIn, b: LegIn): boolean => {
      return samePropKey(a, b) && a.direction === b.direction
    },
    [samePropKey],
  )

  const addLeg = useCallback(
    (leg: LegIn, display: { primary: string; secondary?: string }, americanOdds?: number | null) => {
      const price = americanOdds ?? null
      let added = false
      setLegs((prev) => {
        if (prev.some((r) => sameLeg(r.leg, leg))) return prev
        if (prev.some((r) => samePropKey(r.leg, leg) && r.leg.direction !== leg.direction)) return prev
        added = true
        return [...prev, { id: newRowId(), leg, primary: display.primary, secondary: display.secondary, americanOdds: price }]
      })
      return added
    },
    [sameLeg, samePropKey],
  )

  const hasLeg = useCallback((leg: LegIn) => legs.some((r) => sameLeg(r.leg, leg)), [legs, sameLeg])

  const removeLegByLeg = useCallback((leg: LegIn) => {
    setLegs((prev) => prev.filter((r) => !sameLeg(r.leg, leg)))
  }, [sameLeg])

  const removeLeg = useCallback((id: string) => {
    setLegs((prev) => prev.filter((r) => r.id !== id))
  }, [])

  const clearLegs = useCallback(() => setLegs([]), [])

  const value = useMemo(
    () => ({ legs, addLeg, hasLeg, removeLegByLeg, removeLeg, clearLegs }),
    [legs, addLeg, hasLeg, removeLegByLeg, removeLeg, clearLegs],
  )

  return <BetSlipContext.Provider value={value}>{children}</BetSlipContext.Provider>
}

// Hook is colocated with provider; split file would be redundant for this app.
// eslint-disable-next-line react-refresh/only-export-components -- useBetSlip is a valid companion export
export function useBetSlip(): BetSlipContextValue {
  const ctx = useContext(BetSlipContext)
  if (!ctx) throw new Error('useBetSlip must be used within BetSlipProvider')
  return ctx
}
