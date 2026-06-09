import { describe, expect, it } from 'vitest'
import {
  americanToDecimal,
  combineAmericanParlay,
  combineAmericanParlayPrices,
  decimalToAmerican,
  formatAmericanOdds,
  impliedProbFromAmerican,
  parlayPotentialReturnCents,
  parseAmericanOddsString,
} from './parlayOdds'

describe('parseAmericanOddsString', () => {
  it('parses explicit positive odds', () => {
    expect(parseAmericanOddsString('+150')).toBe(150)
  })

  it('parses negative odds', () => {
    expect(parseAmericanOddsString('-114')).toBe(-114)
  })

  it('treats a bare positive number as positive odds', () => {
    expect(parseAmericanOddsString('220')).toBe(220)
  })

  it('trims surrounding and inner whitespace', () => {
    expect(parseAmericanOddsString('  - 1 1 0 ')).toBe(-110)
  })

  it('returns null for empty or non-numeric input', () => {
    expect(parseAmericanOddsString('')).toBeNull()
    expect(parseAmericanOddsString('abc')).toBeNull()
  })

  it('rejects zero and bare non-positive numbers', () => {
    expect(parseAmericanOddsString('0')).toBeNull()
    expect(parseAmericanOddsString('-0')).toBeNull()
  })
})

describe('americanToDecimal', () => {
  it('converts positive odds', () => {
    expect(americanToDecimal(150)).toBeCloseTo(2.5, 10)
  })

  it('converts negative odds', () => {
    expect(americanToDecimal(-200)).toBeCloseTo(1.5, 10)
  })

  it('returns NaN for zero', () => {
    expect(Number.isNaN(americanToDecimal(0))).toBe(true)
  })
})

describe('impliedProbFromAmerican', () => {
  it('computes implied probability for negative odds', () => {
    expect(impliedProbFromAmerican(-110)).toBeCloseTo(110 / 210, 10)
  })

  it('computes implied probability for positive odds', () => {
    expect(impliedProbFromAmerican(150)).toBeCloseTo(100 / 250, 10)
  })

  it('returns NaN for zero or non-finite odds', () => {
    expect(Number.isNaN(impliedProbFromAmerican(0))).toBe(true)
    expect(Number.isNaN(impliedProbFromAmerican(NaN))).toBe(true)
  })
})

describe('decimalToAmerican', () => {
  it('maps decimal >= 2 to positive american odds', () => {
    expect(decimalToAmerican(2.5)).toBe(150)
  })

  it('maps decimal < 2 to negative american odds', () => {
    expect(decimalToAmerican(1.5)).toBe(-200)
  })

  it('returns NaN for invalid decimals', () => {
    expect(Number.isNaN(decimalToAmerican(1))).toBe(true)
    expect(Number.isNaN(decimalToAmerican(0.5))).toBe(true)
  })

  it('round-trips with americanToDecimal', () => {
    expect(decimalToAmerican(americanToDecimal(150))).toBe(150)
    expect(decimalToAmerican(americanToDecimal(-200))).toBe(-200)
  })
})

describe('formatAmericanOdds', () => {
  it('prefixes positive odds with a plus', () => {
    expect(formatAmericanOdds(150)).toBe('+150')
  })

  it('keeps the minus sign for negative odds', () => {
    expect(formatAmericanOdds(-110)).toBe('-110')
  })

  it('rounds before formatting', () => {
    expect(formatAmericanOdds(149.6)).toBe('+150')
  })
})

describe('combineAmericanParlay', () => {
  it('multiplies decimal payouts across legs', () => {
    const result = combineAmericanParlay([100, 100])
    expect(result).not.toBeNull()
    expect(result!.payoutDecimal).toBeCloseTo(4, 10)
    expect(result!.american).toBe(300)
  })

  it('returns null when any leg is invalid', () => {
    expect(combineAmericanParlay([100, 0])).toBeNull()
  })
})

describe('combineAmericanParlayPrices', () => {
  it('returns the combined american odds', () => {
    expect(combineAmericanParlayPrices([100, 100])).toBe(300)
  })

  it('returns NaN for invalid input', () => {
    expect(Number.isNaN(combineAmericanParlayPrices([0]))).toBe(true)
  })
})

describe('parlayPotentialReturnCents', () => {
  it('rounds stake times payout decimal', () => {
    expect(parlayPotentialReturnCents(1000, 2.5)).toBe(2500)
    expect(parlayPotentialReturnCents(1000, 1.909)).toBe(1909)
  })

  it('returns NaN for non-positive stake', () => {
    expect(Number.isNaN(parlayPotentialReturnCents(0, 2))).toBe(true)
    expect(Number.isNaN(parlayPotentialReturnCents(-100, 2))).toBe(true)
  })

  it('returns NaN for non-finite payout', () => {
    expect(Number.isNaN(parlayPotentialReturnCents(1000, NaN))).toBe(true)
  })
})
