import { expect, test } from '@playwright/test'

test('built application loads and navigates to settings', async ({ page }) => {
  await page.goto('/#/dashboard')
  await expect(page).toHaveTitle('妈妈炒股')
  await expect(page.getByRole('link', { name: '设置' })).toBeVisible()
  await page.getByRole('link', { name: '设置' }).click()
  await expect(page).toHaveURL(/#\/settings$/)
  await expect(page.getByText('🔐 访问令牌')).toBeVisible()
})
