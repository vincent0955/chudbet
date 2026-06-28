import { expect, test } from '@playwright/test'
import { installApiMocks } from './support/mockApi'

test.describe('Home / upcoming games', () => {
  test('renders the schedule with matchup and live market prices', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/')

    await expect(page.getByRole('heading', { name: 'Upcoming games' })).toBeVisible()

    // Teams from the mocked slate.
    await expect(page.getByText('Los Angeles Lakers').first()).toBeVisible()
    await expect(page.getByText('Boston Celtics').first()).toBeVisible()

    // Moneyline prices come from GET /games/:id/markets (loaded after the slate).
    await expect(page.getByText('-150')).toBeVisible()
    await expect(page.getByText('+130')).toBeVisible()
  })

  test('top nav exposes NBA and My Bets', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/')

    const nav = page.getByRole('navigation', { name: 'Main' })
    await expect(nav.getByRole('link', { name: 'NBA' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'My Bets' })).toBeVisible()
  })

  test('clicking a game navigates to its detail page', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/')

    await page.getByText('Boston Celtics').first().click()
    await expect(page).toHaveURL(/\/games\/101$/)
    await expect(page.getByRole('heading', { name: 'Points' })).toBeVisible()
  })
})
