import { describe, expect, it } from 'vitest'
import { formatUsdFromCents } from './formatMoney'

describe('formatUsdFromCents', () => {
  it('formats whole dollars', () => {
    expect(formatUsdFromCents(10000)).toBe('$100.00')
  })

  it('formats cents with two decimals', () => {
    expect(formatUsdFromCents(12345)).toBe('$123.45')
  })

  it('formats zero', () => {
    expect(formatUsdFromCents(0)).toBe('$0.00')
  })

  it('formats negative balances', () => {
    expect(formatUsdFromCents(-2500)).toBe('-$25.00')
  })

  it('adds grouping separators for large amounts', () => {
    expect(formatUsdFromCents(123456789)).toBe('$1,234,567.89')
  })

  it('rounds sub-cent fractions to the nearest cent', () => {
    expect(formatUsdFromCents(100.4)).toBe('$1.00')
    expect(formatUsdFromCents(150.6)).toBe('$1.51')
  })
})
