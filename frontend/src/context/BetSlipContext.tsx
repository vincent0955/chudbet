import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { GameLegIn, LegIn } from '../api/types'

export type SlipLegIn = { kind: 'player'; leg: LegIn } | { kind: 'game'; leg: GameLegIn }

export type SlipLegRow = {
  id: string
  leg: SlipLegIn
  /** Player name (first line on the slip). */
  playerLine: string
  /** Stat / side / line without odds (second line, muted). */
  propLine: string
  /** Optional hint, e.g. browse “last in row”. */
  secondary?: string
  /** Shown once per game group when `leg.game_id` is set (matchup · date from the game page). */
  gameSlipHeader?: string | null
  /** Priced American odds for this selection, when known (e.g. from game props). */
  americanOdds: number | null
}

type BetSlipContextValue = {
  legs: SlipLegRow[]
  addLeg: (
    leg: SlipLegIn,
    display: { playerLine: string; propLine: string; secondary?: string; gameSlipHeader?: string | null },
    americanOdds?: number | null,
  ) => boolean
  hasLeg: (leg: SlipLegIn) => boolean
  removeLegByLeg: (leg: SlipLegIn) => void
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

  const sameLine = useCallback((a: number | null | undefined, b: number | null | undefined) => {
    if (a == null || b == null) return a == null && b == null
    return Math.abs(a - b) < 1e-9
  }, [])

  const sameLeg = useCallback(
    (a: SlipLegIn, b: SlipLegIn): boolean => {
      if (a.kind !== b.kind) return false
      if (a.kind === 'player' && b.kind === 'player') {
        return (
          a.leg.player_id === b.leg.player_id &&
          a.leg.game_id === b.leg.game_id &&
          a.leg.stat_type === b.leg.stat_type &&
          sameLine(a.leg.line, b.leg.line) &&
          a.leg.direction === b.leg.direction
        )
      }
      if (a.kind === 'game' && b.kind === 'game') {
        return (
          a.leg.game_id === b.leg.game_id &&
          a.leg.market_type === b.leg.market_type &&
          a.leg.selection === b.leg.selection &&
          sameLine(a.leg.line, b.leg.line)
        )
      }
      return false
    },
    [sameLine],
  )

  const addLeg = useCallback(
    (
      leg: SlipLegIn,
      display: {
        playerLine: string
        propLine: string
        secondary?: string
        gameSlipHeader?: string | null
      },
      americanOdds?: number | null,
    ) => {
      const price = americanOdds ?? null
      let added = false
      setLegs((prev) => {
        if (prev.some((r) => sameLeg(r.leg, leg))) return prev
        if (
          leg.kind === 'player' &&
          prev.some(
            (r) =>
              r.leg.kind === 'player' &&
              r.leg.leg.player_id === leg.leg.player_id &&
              r.leg.leg.game_id === leg.leg.game_id &&
              r.leg.leg.stat_type === leg.leg.stat_type &&
              sameLine(r.leg.leg.line, leg.leg.line) &&
              r.leg.leg.direction !== leg.leg.direction,
          )
        ) {
          return prev
        }
        added = true
        return [
          ...prev,
          {
            id: newRowId(),
            leg,
            playerLine: display.playerLine,
            propLine: display.propLine,
            secondary: display.secondary,
            gameSlipHeader: display.gameSlipHeader,
            americanOdds: price,
          },
        ]
      })
      return added
    },
    [sameLeg, sameLine],
  )

  const hasLeg = useCallback((leg: SlipLegIn) => legs.some((r) => sameLeg(r.leg, leg)), [legs, sameLeg])

  const removeLegByLeg = useCallback((leg: SlipLegIn) => {
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
