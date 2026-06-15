import { describe, expect, it } from 'vitest'
import {
  classifyMlbStatus,
  gameAcceptsPreGameWagers,
  statusIndicatesLiveOrFinished,
} from './gameWagerGate'

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

describe('classifyMlbStatus', () => {
  it.each(['Scheduled', 'Pre-Game', 'Warmup', ''])('treats %s as pre_game', (status) => {
    expect(classifyMlbStatus(status)).toBe('pre_game')
  })

  it.each(['Final', 'Game Over'])('treats %s as final', (status) => {
    expect(classifyMlbStatus(status)).toBe('final')
  })

  it('treats in-progress as live', () => {
    expect(classifyMlbStatus('In Progress')).toBe('live')
  })
})

describe('gameAcceptsPreGameWagers', () => {
  it('opens MLB scheduled games and closes live/final', () => {
    expect(gameAcceptsPreGameWagers({ sport: 'MLB', status: 'Scheduled' })).toBe(true)
    expect(gameAcceptsPreGameWagers({ sport: 'MLB', status: 'In Progress' })).toBe(false)
    expect(gameAcceptsPreGameWagers({ sport: 'MLB', status: 'Final' })).toBe(false)
  })

  it('keeps NBA heuristic behavior', () => {
    expect(gameAcceptsPreGameWagers({ sport: 'NBA', status: '7:30 pm ET' })).toBe(true)
    expect(gameAcceptsPreGameWagers({ sport: 'NBA', status: 'Q3 2:00' })).toBe(false)
  })
})
