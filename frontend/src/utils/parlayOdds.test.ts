import { describe, expect, it } from 'vitest'
import { impliedProbFromAmerican, priceParlayByMode } from './parlayOdds'

function approxEqual(a: number, b: number, eps = 1e-9): boolean {
  return Math.abs(a - b) <= eps
}

describe('priceParlayByMode', () => {
  it('prices standard hit as all-legs-hit probability', () => {
    const priced = priceParlayByMode([-110, -110], {
      mode: 'standard',
      wagerOnHit: true,
      marginRate: 0,
    })
    expect(priced).not.toBeNull()
    const p = impliedProbFromAmerican(-110)
    expect(approxEqual(priced!.pTicket, p * p)).toBe(true)
  })

  it('prices anti standard as complement of all-legs-hit', () => {
    const priced = priceParlayByMode([-110, -110], {
      mode: 'standard',
      wagerOnHit: false,
      marginRate: 0,
    })
    expect(priced).not.toBeNull()
    const p = impliedProbFromAmerican(-110)
    expect(approxEqual(priced!.pTicket, 1 - p * p)).toBe(true)
  })

  it('prices x_of_y hit as P(H >= k)', () => {
    const priced = priceParlayByMode([-110, -110], {
      mode: 'x_of_y',
      kRequired: 1,
      wagerOnHit: true,
      marginRate: 0,
    })
    expect(priced).not.toBeNull()
    const p = impliedProbFromAmerican(-110)
    expect(approxEqual(priced!.pTicket, 1 - (1 - p) * (1 - p))).toBe(true)
  })

  it('prices anti x_of_y as P(H < k)', () => {
    const priced = priceParlayByMode([-110, -110], {
      mode: 'x_of_y',
      kRequired: 2,
      wagerOnHit: false,
      marginRate: 0,
    })
    expect(priced).not.toBeNull()
    const p = impliedProbFromAmerican(-110)
    expect(approxEqual(priced!.pTicket, 1 - p * p)).toBe(true)
  })

  it('returns null for invalid k', () => {
    const priced = priceParlayByMode([120, -150], {
      mode: 'x_of_y',
      kRequired: 3,
      wagerOnHit: true,
    })
    expect(priced).toBeNull()
  })

  it('keeps selected side near original book price for single leg', () => {
    const priced = priceParlayByMode([-120], {
      mode: 'standard',
      wagerOnHit: true,
    })
    expect(priced).not.toBeNull()
    expect(priced!.american).toBe(-120)
  })

  it('prices anti side as paired two-way book side (single -120 -> around -108)', () => {
    const priced = priceParlayByMode([-120], {
      mode: 'standard',
      wagerOnHit: false,
    })
    expect(priced).not.toBeNull()
    expect(priced!.american).toBe(-108)
  })
})
