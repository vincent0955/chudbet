import { describe, expect, it } from 'vitest'
import {
  formatGameDate,
  formatHalfPointLine,
  formatStat,
  formatTipOrGameStatusLabel,
} from './format'

describe('formatStat', () => {
  it('renders integers without decimals', () => {
    expect(formatStat(20)).toBe('20')
  })

  it('renders fractional values with one decimal by default', () => {
    expect(formatStat(20.5)).toBe('20.5')
    expect(formatStat(20.567)).toBe('20.6')
  })

  it('honors a custom max fraction digits', () => {
    expect(formatStat(20.567, 2)).toBe('20.57')
  })
})

describe('formatHalfPointLine', () => {
  it('always ends in .5', () => {
    expect(formatHalfPointLine(20)).toBe('20.5')
    expect(formatHalfPointLine(20.4)).toBe('20.5')
    expect(formatHalfPointLine(20.6)).toBe('20.5')
    expect(formatHalfPointLine(19.2)).toBe('19.5')
  })

  it('handles values already at a half point', () => {
    expect(formatHalfPointLine(24.5)).toBe('24.5')
  })
})

describe('formatGameDate', () => {
  it('falls back to the raw string for malformed dates', () => {
    expect(formatGameDate('not-a-date')).toBe('not-a-date')
    expect(formatGameDate('')).toBe('')
  })

  it('produces a non-empty label for a valid ISO date', () => {
    const label = formatGameDate('2026-01-15')
    expect(label).not.toBe('2026-01-15')
    expect(label.length).toBeGreaterThan(0)
  })
})

describe('formatTipOrGameStatusLabel', () => {
  it('returns null when neither tip time nor status is usable', () => {
    expect(formatTipOrGameStatusLabel(null, null)).toBeNull()
    expect(formatTipOrGameStatusLabel(undefined, '   ')).toBeNull()
  })

  it('falls back to game status when there is no UTC tip time', () => {
    expect(formatTipOrGameStatusLabel(null, 'Final')).toBe('Final')
  })

  it('prefers a formatted tip time over the status text', () => {
    const label = formatTipOrGameStatusLabel('2026-01-15T23:30:00Z', 'Scheduled')
    expect(label).not.toBe('Scheduled')
    expect(label).not.toBeNull()
  })
})
