import { expect, test } from '@playwright/test'
import { installApiMocks } from './support/mockApi'

test.describe('Game detail & prop board', () => {
  test('renders prop sections and players for the game', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/games/101')

    await expect(page.getByRole('heading', { name: 'Points' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Rebounds' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Assists' })).toBeVisible()

    await expect(page.getByText('LeBron James').first()).toBeVisible()
    await expect(page.getByText('Jayson Tatum').first()).toBeVisible()
  })

  test('adding a player prop puts a leg on the bet slip', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/games/101')

    await expect(page.getByText('Bet slip')).toBeVisible()
    await expect(page.getByText('0 legs')).toBeVisible()

    await page.getByRole('button', { name: /O 27\.5/ }).first().click()

    await expect(page.getByText('1 leg', { exact: true })).toBeVisible()
    // The slip lists the picked prop.
    await expect(page.getByText('PTS OVER 27.5')).toBeVisible()
  })

  test('selecting Over then Under for the same prop keeps a single leg', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/games/101')

    await page.getByRole('button', { name: /O 27\.5/ }).first().click()
    await expect(page.getByText('1 leg', { exact: true })).toBeVisible()

    // Picking the opposite side swaps it rather than stacking a contradictory leg.
    await page.getByRole('button', { name: /U 27\.5/ }).first().click()
    await expect(page.getByText('1 leg', { exact: true })).toBeVisible()
    await expect(page.getByText('PTS UNDER 27.5')).toBeVisible()
  })

  test('unknown game id shows a not-found message', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/games/999999')

    await expect(page.getByText('Game not found')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Back home' })).toBeVisible()
  })
})
