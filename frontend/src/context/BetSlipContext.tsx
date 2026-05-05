import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { LegIn } from '../api/types'

export type SlipLegRow = {
  id: string
  leg: LegIn
  /** Short label, e.g. player · stat · O/U line */
  primary: string
  /** Optional context, e.g. game date or matchup */
  secondary?: string
}

type BetSlipContextValue = {
  legs: SlipLegRow[]
  addLeg: (leg: LegIn, display: { primary: string; secondary?: string }) => void
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

  const addLeg = useCallback((leg: LegIn, display: { primary: string; secondary?: string }) => {
    setLegs((prev) => [...prev, { id: newRowId(), leg, primary: display.primary, secondary: display.secondary }])
  }, [])

  const removeLeg = useCallback((id: string) => {
    setLegs((prev) => prev.filter((r) => r.id !== id))
  }, [])

  const clearLegs = useCallback(() => setLegs([]), [])

  const value = useMemo(
    () => ({ legs, addLeg, removeLeg, clearLegs }),
    [legs, addLeg, removeLeg, clearLegs],
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
