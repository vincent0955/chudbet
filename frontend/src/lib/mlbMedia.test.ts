import { describe, expect, it } from 'vitest'
import { mlbPlayerHeadshotUrl, mlbTeamLogoUrl } from './mlbMedia'

describe('mlbTeamLogoUrl', () => {
  it('returns null for missing or non-finite ids', () => {
    expect(mlbTeamLogoUrl(null)).toBeNull()
    expect(mlbTeamLogoUrl(undefined)).toBeNull()
    expect(mlbTeamLogoUrl(Number.NaN)).toBeNull()
    expect(mlbTeamLogoUrl(Number.POSITIVE_INFINITY)).toBeNull()
  })

  it('Feature: mlb-support, Property 20 — numeric team ids resolve to mlbstatic URLs', () => {
    for (let i = 0; i < 120; i += 1) {
      const id = 1 + ((i * 7919) % 99999)
      expect(mlbTeamLogoUrl(id)).toBe(`https://www.mlbstatic.com/team-logos/${id}.svg`)
    }
  })
})

describe('mlbPlayerHeadshotUrl', () => {
  it('Feature: mlb-support, Property 20 — numeric player ids resolve to headshot URLs', () => {
    for (let i = 0; i < 120; i += 1) {
      const id = 1 + ((i * 6151) % 999999)
      expect(mlbPlayerHeadshotUrl(id)).toBe(
        `https://midfield.mlbstatic.com/v1/people/${id}/spots/120`,
      )
    }
  })

  it('Feature: mlb-support, Property 20 — invalid ids degrade to null', () => {
    for (const bad of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY] as const) {
      expect(mlbPlayerHeadshotUrl(bad)).toBeNull()
    }
  })
})
