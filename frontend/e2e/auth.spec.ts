import { expect, test } from '@playwright/test'
import { installApiMocks } from './support/mockApi'

test.describe('Authentication & wallet', () => {
  test('guest login shows the wallet balance, logout clears it', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/')

    // Logged out: no balance shown.
    await expect(page.locator('.app-header__balance')).toHaveCount(0)

    // Opening the profile menu reveals the auth actions; it stays open across the
    // login state change, so we click "Log out" without re-toggling it.
    await page.getByLabel('Profile menu').click()
    await page.getByRole('button', { name: 'Log in as guest' }).click()

    await expect(page.locator('.app-header__balance')).toHaveText('$50,000.00')

    await page.getByRole('button', { name: 'Log out' }).click()
    await expect(page.locator('.app-header__balance')).toHaveCount(0)
    await expect(page.getByText('Logged out')).toBeVisible()
  })

  test('signup page can continue as guest and returns home', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/signup')

    const form = page.locator('section.signup-page')
    await expect(form.getByRole('heading', { name: 'Sign up' })).toBeVisible()
    await form.getByRole('button', { name: 'Log in as guest' }).click()

    await expect(page).toHaveURL(/\/$/)
    await expect(page.locator('.app-header__balance')).toHaveText('$50,000.00')
  })

  test('signup with matching passwords logs the user in', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/signup')

    const form = page.locator('section.signup-page')
    await form.getByPlaceholder('Email').fill('fan@example.com')
    await form.getByPlaceholder('Username').fill('hoopsfan')
    await form.getByPlaceholder('Password', { exact: true }).fill('hunter2hunter2')
    await form.getByPlaceholder('Confirm password').fill('hunter2hunter2')
    await form.getByRole('button', { name: 'Sign up' }).click()

    await expect(page).toHaveURL(/\/$/)
    await expect(page.locator('.app-header__balance')).toHaveText('$50,000.00')
  })

  test('signup blocks mismatched passwords client-side', async ({ page }) => {
    await installApiMocks(page)
    await page.goto('/signup')

    const form = page.locator('section.signup-page')
    await form.getByPlaceholder('Email').fill('fan@example.com')
    await form.getByPlaceholder('Username').fill('hoopsfan')
    await form.getByPlaceholder('Password', { exact: true }).fill('hunter2hunter2')
    await form.getByPlaceholder('Confirm password').fill('different')
    await form.getByRole('button', { name: 'Sign up' }).click()

    await expect(page.getByText('Passwords do not match')).toBeVisible()
    await expect(page).toHaveURL(/\/signup$/)
  })
})
