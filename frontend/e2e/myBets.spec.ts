import { expect, test } from '@playwright/test'
import { openPendingWager, settledWonWager } from './support/fixtures'
import { installApiMocks } from './support/mockApi'

test.describe('My Bets', () => {
  test('logged-out users are asked to log in', async ({ page }) => {
    await installApiMocks(page, { loggedIn: false })
    await page.goto('/bets/open')

    await expect(page.getByRole('heading', { name: 'My Bets' })).toBeVisible()
    await expect(page.getByText('Log in or continue as guest to place bets and see them here.')).toBeVisible()
  })

  test('open tab lists open wagers with leg details', async ({ page }) => {
    await installApiMocks(page, { loggedIn: true, seedWagers: [openPendingWager(), settledWonWager()] })
    await page.goto('/bets/open')

    await expect(page.getByText('1 leg parlay')).toBeVisible()
    await expect(page.locator('.my-bets__pill--open')).toBeVisible()
    await expect(page.getByText('LeBron James · PTS OVER 27.5')).toBeVisible()
    await expect(page.getByText('Wager: $50.00')).toBeVisible()

    // The settled (won) wager must not appear under the Open tab.
    await expect(page.locator('.my-bets__pill--won')).toHaveCount(0)
  })

  test('settled tab lists graded wagers with outcome and payout', async ({ page }) => {
    await installApiMocks(page, { loggedIn: true, seedWagers: [openPendingWager(), settledWonWager()] })
    await page.goto('/bets/settled')

    await expect(page.locator('.my-bets__pill--won')).toBeVisible()
    await expect(page.getByText('Boston Celtics · MONEYLINE (-150)')).toBeVisible()
    await expect(page.getByText('Payout: $250.00')).toBeVisible()

    await expect(page.locator('.my-bets__pill--open')).toHaveCount(0)
  })

  test('can switch between Open and Settled tabs', async ({ page }) => {
    await installApiMocks(page, { loggedIn: true, seedWagers: [openPendingWager(), settledWonWager()] })
    await page.goto('/bets/open')

    await expect(page.locator('.my-bets__pill--open')).toBeVisible()

    await page.getByRole('link', { name: 'Settled' }).click()
    await expect(page).toHaveURL(/\/bets\/settled$/)
    await expect(page.locator('.my-bets__pill--won')).toBeVisible()
  })
})
