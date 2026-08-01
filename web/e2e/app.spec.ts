import { expect, test, type Page } from '@playwright/test'

const quote = {
  code: '600519',
  name: '贵州茅台',
  market: 'SH',
  price: '1680.50',
  change: '30.50',
  change_pct: '1.85',
  volume: 12_345_678,
  turnover: '2000000000',
  open: '1660.00',
  high: '1690.00',
  low: '1655.00',
  prev_close: '1650.00',
  pe: '25.6',
  pb: '8.1',
  turnover_rate: '0.98',
  volume_ratio: '1.23',
  main_net_inflow: '120000000',
  timestamp: '2026-07-25T15:00:00Z',
  fetched_at: '2026-07-25T15:00:01Z',
  data_age_seconds: 1,
}

const secondQuote = {
  ...quote,
  code: '000858',
  name: '五粮液',
  market: 'SZ',
  price: '122.00',
}

const overview = {
  indexes: {
    indexes: [
      { name: '上证指数', price: '3388.80', change_pct: '0.65' },
      { name: '深证成指', price: '10600.10', change_pct: '-0.20' },
      { name: '创业板指', price: '2200.30', change_pct: '0.42' },
      { name: '沪深300', price: '3980.00', change_pct: '0.31' },
    ],
    block: { status: 'ok', as_of: '2026-07-25T15:00:00Z', message: null },
  },
  themes: {
    items: [
      { id: 'semiconductor', name: '半导体', description: '国产产业链', total_stocks: 12 },
      { id: 'innovative_drug', name: '创新药', description: '创新药产业链', total_stocks: 8 },
    ],
    block: { status: 'ok', as_of: '2026-07-25T15:00:00Z', message: null },
  },
  watchlist: {
    total: 1, n_up: 1, n_down: 0, n_flat: 0,
    items: [{ code: '600519', name: '贵州茅台', price: '1680.50', change_pct: '1.85', group: '默认', data_age_seconds: 1 }],
    block: { status: 'ok', as_of: '2026-07-25T15:00:00Z', message: null },
  },
  portfolio: {
    n_positions: 0, total_unrealized_pnl: null, total_unrealized_pnl_pct: null, alerts: [],
    block: { status: 'ok', as_of: '2026-07-25T15:00:00Z', message: '无持仓' },
  },
  signals: {
    summary: null,
    block: { status: 'ok', as_of: '2026-07-25T15:00:00Z', message: '暂无信号' },
  },
}

async function mockApi(page: Page) {
  let watchlistAdded = false
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

    if (path === '/api/auth/status') return json({ mode: 'none', authenticated: true, llm_configured: true })
    if (path === '/api/setup/status') return json({
      auth_mode: 'none', llm_configured: true, provider: 'deepseek', model: 'deepseek-chat',
      weixin: { connected: false, online: false }, data_ok: true,
    })
    if (path === '/api/setup/providers') return json([
      { id: 'deepseek', label: 'DeepSeek', default_model: 'deepseek-chat', env_key: 'DEEPSEEK_API_KEY' },
    ])
    if (path === '/api/auth/pair' && request.method() === 'POST') return json({ ok: true, message: '配对成功' })
    if (path === '/api/setup/weixin/start' && request.method() === 'POST') return json({
      pairing_id: 'test-pid', qr_data_url: 'data:image/svg+xml;base64,PHN2Zy8+',
      expires_in_seconds: 480, status: 'waiting', message: '请扫码',
    })
    if (path === '/api/setup/weixin/poll' && request.method() === 'POST') return json({
      status: 'connected', message: '成功', gateway_started: true, gateway_online: true,
    })
    if (path === '/api/health') return json({ ok: true, adapter_name: 'Mock', uptime_seconds: 42, last_snapshot_at: null })
    if (path === '/api/agent/history') return json({ messages: [], total: 0 })
    if (path === '/api/agent/predictions') return json({ predictions: [], total: 0 })
    if (path === '/api/agent/route' && request.method() === 'POST') {
      return json({ matched: true, workflow_id: 'stock_analysis', reply: '茅台基本面稳健，注意估值与仓位。', steps: [] })
    }
    if (path === '/api/overview') return json(overview)
    if (path === '/api/themes') return json({ items: overview.themes.items, total: 2 })
    if (path === '/api/themes/semiconductor') return json({
      ...overview.themes.items[0], subcategories: ['设备'], stocks: [{ code: '600519', name: '贵州茅台' }],
    })
    if (path === '/api/themes/semiconductor/quotes') return json({
      items: [{ ...quote, subcategory: '设备', level: '设备', role: '', growth_text: '', growth_low: null, growth_high: null, core_driver: '', highlight: '' }],
      total: 1,
    })
    if (path === '/api/market/indexes') {
      return json([{ code: 'sh000001', name: '上证指数', price: '3388.80', change_pct: '0.65', prev_close: '3366.90' }])
    }
    if (path === '/api/market/gainers' || path === '/api/market/losers' || path === '/api/market/sectors') return json([])
    if (path === '/api/quotes') {
      return json({ timestamp: '2026-07-25T15:00:00Z', quotes: [quote], total_main_net: '120000000', n_codes: 1, n_up: 1, n_down: 0, n_flat: 0 })
    }
    if (path === '/api/quotes/600519') return json(quote)
    if (path === '/api/quotes/000858') return json(secondQuote)
    if (path === '/api/quotes/600519/bars') return json([])
    if (path === '/api/quotes/000858/bars') return json([])
    if (path.includes('/money_flow/')) return json({ items: [], cumulative: { main_net: '0', super_net: '0', big_net: '0', medium_net: '0', small_net: '0' } })
    if (path === '/api/signals/recent') return json([])
    if (path === '/api/watchlist/groups') return json([{ name: '默认', description: '', n_stocks: watchlistAdded ? 1 : 0 }])
    if (path === '/api/watchlist' && request.method() === 'GET') {
      return json(watchlistAdded ? [{ code: '600519', name: '贵州茅台', group: '默认', note: '', added_at: '2026-07-25T15:00:00Z' }] : [])
    }
    if (path === '/api/watchlist/stocks' && request.method() === 'POST') {
      watchlistAdded = true
      return json({ code: '600519', name: '贵州茅台', group: '默认', note: '', added_at: '2026-07-25T15:00:00Z' }, 201)
    }
    if (path === '/api/portfolio') return json({ positions: [], total_cost: '0', total_market_value: '0', total_unrealized_pnl: '0', total_unrealized_pnl_pct: '0', n_positions: 0 })
    if (path === '/api/cache/stats') return json({ hits: 0, fetches: 0, fetch_ok: 0, fetch_fail: 0, miss: 0, hit_rate: 0, freshness: [] })
    return json([])
  })
}

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('desktop starts with Today and exposes the focused navigation', async ({ page }) => {
  await page.goto('/#/')
  await expect(page).toHaveTitle('妈妈炒股')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: '跳到主要内容' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main-content')).toBeFocused()

  const navigation = page.getByRole('navigation', { name: '主导航' })
  await expect(navigation.getByRole('link')).toHaveCount(6)
  await expect(navigation.getByRole('link', { name: '今日' })).toBeVisible()
  await expect(navigation.getByRole('link', { name: '关注' })).toBeVisible()
  await expect(navigation.getByRole('link', { name: '持仓' })).toBeVisible()
  await expect(navigation.getByRole('link', { name: '问AI' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '今日' })).toBeVisible()
  await expect(page.getByText('上证指数')).toBeVisible()
  await expect(page.getByRole('link', { name: /贵州茅台/ }).first()).toBeVisible()

  await navigation.getByRole('link', { name: '我的' }).click()
  await expect(page).toHaveURL(/#\/my$/)
  // Token UI removed — status center visible instead
  await expect(page.getByText('⚙️ 配置状态')).toBeVisible()
  // Theme is always visible now (not gated on authMode === 'token')
  await expect(page.getByText('🎨 主题')).toBeVisible()
  // No access token UI
  await expect(page.getByText('🔐 访问令牌')).not.toBeVisible()
})

test('mobile four-tab navigation preserves a multiline chat draft', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#/')

  const mobileNav = page.getByRole('navigation', { name: '移动端主导航' })
  await expect(mobileNav.getByRole('link')).toHaveCount(4)
  await mobileNav.getByRole('link', { name: '问AI' }).click()
  const prompt = page.getByRole('textbox', { name: '输入投研问题' })
  await prompt.fill('稍后继续分析\n比亚迪')
  await mobileNav.getByRole('link', { name: '关注' }).click()
  await mobileNav.getByRole('link', { name: '问AI' }).click()
  await expect(prompt).toHaveValue('稍后继续分析\n比亚迪')
})

test('mobile Today leads to detail, add-watchlist, and ask-AI loop', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/#/')

  await page.getByRole('link', { name: /贵州茅台/ }).click()
  await expect(page).toHaveURL(/#\/detail\/600519$/)

  await page.getByRole('button', { name: '☆ 加自选' }).click()
  await expect(page.getByRole('button', { name: '★ 已在自选' })).toBeVisible()
  await page.getByRole('button', { name: '🤖 问问 AI' }).click()

  await expect(page).toHaveURL(/#\/chat/)
  await expect(page.getByText('分析一下贵州茅台（600519）')).toBeVisible()
  await expect(page.getByText('茅台基本面稳健，注意估值与仓位。')).toBeVisible()
})

test('normal Today bootstrap uses auth plus overview without setup status', async ({ page }) => {
  const bootstrapPaths: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path === '/api/auth/status' || path === '/api/setup/status' || path === '/api/overview') {
      bootstrapPaths.push(path)
    }
  })

  await page.goto('/#/')
  await expect(page.getByRole('heading', { name: '今日' })).toBeVisible()
  expect(bootstrapPaths.filter((path) => path === '/api/auth/status')).toHaveLength(1)
  expect(bootstrapPaths.filter((path) => path === '/api/overview')).toHaveLength(1)
  expect(bootstrapPaths).not.toContain('/api/setup/status')
})

test('detail tabs lazy-load, deep-link, and reload for a new stock', async ({ page }) => {
  const barsRequests: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path.endsWith('/bars')) barsRequests.push(path)
  })

  await page.goto('/#/detail/600519')
  await expect(page.getByRole('heading', { name: '贵州茅台' })).toBeVisible()
  expect(barsRequests).toEqual([])

  await page.getByRole('tab', { name: '走势' }).click()
  await expect(page).toHaveURL(/detail\/600519\?tab=chart$/)
  await expect.poll(() => barsRequests).toEqual(['/api/quotes/600519/bars'])

  await page.getByRole('textbox', { name: '股票代码' }).fill('000858')
  await page.getByRole('textbox', { name: '股票代码' }).press('Enter')
  await expect(page).toHaveURL(/detail\/000858\?tab=chart$/)
  await expect(page.getByRole('heading', { name: '五粮液' })).toBeVisible()
  await expect.poll(() => barsRequests).toEqual([
    '/api/quotes/600519/bars',
    '/api/quotes/000858/bars',
  ])
})

test('capture release screenshots', async ({ page }) => {
  test.skip(!process.env.UPDATE_SCREENSHOTS, 'Only runs when refreshing README assets')

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#/')
  await expect(page.getByRole('heading', { name: '今日' })).toBeVisible()
  await page.screenshot({ path: '../docs/images/web-today.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#/')
  await expect(page.getByRole('heading', { name: '今日' })).toBeVisible()
  await page.waitForTimeout(300)
  await page.screenshot({ path: '../docs/images/web-today-mobile.png', fullPage: true })
})

// ---------- Phase 3B: onboarding / pairing tests ----------

test('configured app /my shows status center with reconfigure targets', async ({ page }) => {
  await page.goto('/#/my')
  await expect(page.getByText('⚙️ 配置状态')).toBeVisible()
  await expect(page.getByText('AI 助手')).toBeVisible()
  await expect(page.getByText('已配置')).toBeVisible()
  await expect(page.getByText('微信通道', { exact: true })).toBeVisible()
  await expect(page.getByText('未连接')).toBeVisible()
  // No token UI
  await expect(page.getByText('🔐 访问令牌')).not.toBeVisible()
  // Theme always visible
  await expect(page.getByText('🎨 主题')).toBeVisible()
  // Reconfigure links use correct labels + query params
  const aiBtn = page.getByRole('link', { name: '重新配置 AI' })
  await expect(aiBtn).toBeVisible()
  await expect(aiBtn).toHaveAttribute('href', /step=ai/)
  const wxBtn = page.getByRole('link', { name: '连接微信' })
  await expect(wxBtn).toBeVisible()
  await expect(wxBtn).toHaveAttribute('href', /step=weixin/)
})

test('remote pairing: redirect from normal route, code entry, transition', async ({ page }) => {
  // State: unauthenticated pairing mode, setup/status returns 401 until paired
  let paired = false
  let unauthorizedSetupCalls = 0
  await page.route('**/api/auth/status', async (route) => {
    if (paired) {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ mode: 'pairing', authenticated: true }),
      })
    } else {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ mode: 'pairing', authenticated: false }),
      })
    }
  })
  await page.route('**/api/setup/status', async (route) => {
    if (!paired) {
      unauthorizedSetupCalls++
      await route.fulfill({ status: 401, body: JSON.stringify({ detail: 'unauthorized' }) })
    } else {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          auth_mode: 'pairing', llm_configured: true, provider: 'deepseek', model: 'deepseek-chat',
          weixin: { connected: false, online: false }, data_ok: true,
        }),
      })
    }
  })
  await page.route('**/api/auth/pair', async (route) => {
    paired = true
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: '配对成功' }),
    })
  })

  // Navigate to a normal route — should redirect to /setup
  await page.goto('/#/market')
  await expect(page).toHaveURL(/#\/setup/)
  // Pairing code entry visible
  await expect(page.getByRole('heading', { name: '输入配对码' })).toBeVisible()
  // /setup is outside nav shell — no sidebar nav
  await expect(page.getByRole('navigation', { name: '主导航' })).not.toBeVisible()
  await expect(page.getByRole('navigation', { name: '移动端主导航' })).not.toBeVisible()
  expect(unauthorizedSetupCalls).toBe(0)

  // Enter code and submit
  await page.getByRole('textbox', { name: '6 位配对码' }).fill('123456')
  await page.getByRole('button', { name: '配对' }).click()

  // After pairing, should transition to weixin step (authenticated, llm_configured)
  await expect(page.getByRole('heading', { name: '连接微信消息通道' })).toBeVisible()
})

test('setup query targets open the requested reconfiguration step outside the app shell', async ({ page }) => {
  await page.goto('/#/setup?step=ai&returnTo=/my')
  await expect(page.getByRole('heading', { name: '配置 AI 助手' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '连接微信消息通道' })).not.toBeVisible()
  await expect(page.getByRole('navigation', { name: '主导航' })).not.toBeVisible()

  await page.goto('/#/setup?step=weixin&returnTo=/my')
  await expect(page.getByRole('heading', { name: '连接微信消息通道' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '配置 AI 助手' })).not.toBeVisible()
  await expect(page.getByRole('navigation', { name: '主导航' })).not.toBeVisible()
})

test('first-run without LLM config shows AI step on /setup', async ({ page }) => {
  await page.route('**/api/auth/status', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ mode: 'none', authenticated: true }),
    })
  })
  await page.route('**/api/setup/status', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        auth_mode: 'none', llm_configured: false, provider: 'deepseek', model: '',
        weixin: { connected: false, online: false }, data_ok: true,
      }),
    })
  })

  await page.goto('/#/setup')
  await expect(page.getByRole('heading', { name: '配置 AI 助手' })).toBeVisible()
})

test('Weixin start is not requested before explicit user click', async ({ page }) => {
  await page.route('**/api/auth/status', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ mode: 'none', authenticated: true }),
    })
  })
  await page.route('**/api/setup/status', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        auth_mode: 'none', llm_configured: true, provider: 'deepseek', model: 'deepseek-chat',
        weixin: { connected: false, online: false }, data_ok: true,
      }),
    })
  })

  let weixinStartCount = 0
  page.on('request', (request) => {
    if (request.url().includes('/api/setup/weixin/start')) weixinStartCount++
  })

  await page.goto('/#/setup')
  await expect(page.getByRole('heading', { name: '连接微信消息通道' })).toBeVisible()
  await expect(page.getByRole('button', { name: '显示微信二维码' })).toBeVisible()
  await expect(page.getByRole('button', { name: '以后再说' })).toBeVisible()

  await page.waitForTimeout(1000)
  expect(weixinStartCount).toBe(0)
})
