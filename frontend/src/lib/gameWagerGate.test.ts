import { describe, expect, it } from 'vitest'
import { statusIndicatesLiveOrFinished } from './gameWagerGate'

describe('statusIndicatesLiveOrFinished', () => {
  it.each([
    'Final',
    'FINAL/OT',
    'Postponed',
    'Cancelled',
    'Halftime',
    'End of 2nd Qtr',
    '1st Qtr 5:00',
    'Q3 2:11',
    'OT 1:00',
    '5:30',
  ])('treats live/finished status %s as not wagerable', (status) => {
    expect(statusIndicatesLiveOrFinished(status)).toBe(true)
  })

  it.each([null, undefined, '', '   ', '7:30 pm ET', '10:00 AM', '8:00 PM ET', 'Scheduled'])(
    'treats pre-game status %s as wagerable',
    (status) => {
      expect(statusIndicatesLiveOrFinished(status)).toBe(false)
    },
  )

  it('is case insensitive', () => {
    expect(statusIndicatesLiveOrFinished('final')).toBe(true)
    expect(statusIndicatesLiveOrFinished('FINAL')).toBe(true)
  })

  it('matches the backend gate for the same inputs', () => {
    // Mirrors backend status_indicates_live_or_finished parity contract.
    expect(statusIndicatesLiveOrFinished('Q1 12:00')).toBe(true)
    expect(statusIndicatesLiveOrFinished('7:30 PM ET')).toBe(false)
  })
})
