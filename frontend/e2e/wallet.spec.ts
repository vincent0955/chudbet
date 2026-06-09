import { expect, test } from '@playwright/test'
import { installApiMocks } from './support/mockApi'

test.describe('Wallet deposit', () => {
  test('Add money credits the balance', async ({ page }) => {
    await installApiMocks(page, { loggedIn: true })
    await page.goto('/')

    await expect(page.locator('.app-header__balance')).toHaveText('$50,000.00')

    // The "Add money" action uses window.prompt for the amount.
    page.once('dialog', (dialog) => {
      expect(dialog.type()).toBe('prompt')
      void dialog.accept('250')
    })

    await page.getByLabel('Profile menu').click()
    await page.getByRole('button', { name: 'Add money' }).click()

    await expect(page.locator('.app-header__balance')).toHaveText('$50,250.00')
  })
})
