import { expect, test } from '@playwright/test'

test('built application loads and navigates to settings', async ({ page }) => {
  await page.goto('/#/dashboard')
  await expect(page).toHaveTitle('妈妈炒股')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: '跳到主要内容' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main-content')).toBeFocused()
  await expect(page.getByRole('link', { name: '设置' })).toBeVisible()
  await page.getByRole('link', { name: '设置' }).click()
  await expect(page).toHaveURL(/#\/settings$/)
  await expect(page.getByText('🔐 访问令牌')).toBeVisible()
})

test('mobile navigation preserves the chat draft and deep-links signal tabs', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#/agent')

  const prompt = page.getByRole('textbox', { name: '给 AI 助手的消息' })
  await prompt.fill('稍后继续分析比亚迪')
  await page.getByRole('link', { name: '行情' }).click()
  await page.getByRole('link', { name: 'AI对话' }).click()
  await expect(prompt).toHaveValue('稍后继续分析比亚迪')

  await page.getByRole('link', { name: '信号' }).click()
  await page.getByRole('tab', { name: /历史信号/ }).click()
  await expect(page).toHaveURL(/#\/signals\?tab=history$/)
})
