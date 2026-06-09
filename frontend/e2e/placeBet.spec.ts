import { expect, test } from '@playwright/test'
import { installApiMocks } from './support/mockApi'

test.describe('Place a bet (end to end)', () => {
  test('builds a parlay from a prop, prices it, and places the wager', async ({ page }) => {
    const mock = await installApiMocks(page, { loggedIn: true })
    await page.goto('/games/101')

    await expect(page.locator('.app-header__balance')).toHaveText('$50,000.00')

    // Add a priced player prop (carries -110 odds).
    await page.getByRole('button', { name: /O 27\.5/ }).first().click()
    await expect(page.getByText('1 leg', { exact: true })).toBeVisible()

    // Combined odds should be priced (not the "—" placeholder).
    await expect(page.locator('.bet-slip__combined-value')).not.toHaveText('—')

    // Enter a stake and confirm the payout preview appears.
    await page.getByLabel('Wager').fill('100')
    await expect(page.locator('.bet-slip__payoff-value')).toBeVisible()

    const placeBet = page.getByRole('button', { name: 'Place bet' })
    await expect(placeBet).toBeEnabled()
    await placeBet.click()

    // Redirects to the open bets tab and the new wager is listed.
    await expect(page).toHaveURL(/\/bets\/open$/)
    await expect(page.getByText('1 leg parlay')).toBeVisible()
    await expect(page.locator('.my-bets__pill--open')).toBeVisible()

    expect(mock.placedCount()).toBe(1)

    // Balance reflects the debited stake after the post-place refresh.
    await expect(page.locator('.app-header__balance')).toHaveText('$49,900.00')
  })

  test('logged-out users are prompted to log in when placing a bet', async ({ page }) => {
    const mock = await installApiMocks(page, { loggedIn: false })
    await page.goto('/games/101')

    await page.getByRole('button', { name: /O 27\.5/ }).first().click()
    await page.getByLabel('Wager').fill('100')

    await page.getByRole('button', { name: 'Place bet' }).click()

    await expect(page.getByText('Log in from the profile menu to place a bet.')).toBeVisible()
    await expect(page).toHaveURL(/\/games\/101$/)
    expect(mock.placedCount()).toBe(0)
  })
})
