import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  apiDelete,
  apiGet,
  apiPost,
  authenticatedWsUrl,
  authMode,
  authRequired,
  getApiToken,
  getChatSessionId,
  loadAuthStatus,
  setApiToken,
  toApiError,
} from './client'

function mockResponseOnce(status: number, body = 'x') {
  vi.mocked(fetch).mockResolvedValueOnce(new Response(body, { status }))
}

describe('authenticated API state', () => {
  beforeEach(() => {
    sessionStorage.clear()
    authRequired.value = false
    authMode.value = 'unknown'
    vi.stubGlobal('fetch', vi.fn())
  })

  it('normalizes and persists the owner token for one tab', () => {
    setApiToken('  owner-secret  ')
    expect(getApiToken()).toBe('owner-secret')
    setApiToken(' ')
    expect(getApiToken()).toBe('')
  })

  it('creates one stable chat session id', () => {
    const first = getChatSessionId()
    expect(first).toMatch(/^web-/)
    expect(getChatSessionId()).toBe(first)
  })

  it('attaches bearer auth and reports failed requests', async () => {
    setApiToken('owner-secret')
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    )
    await expect(apiGet<{ ok: boolean }>('/api/health')).resolves.toEqual({ ok: true })
    expect(fetch).toHaveBeenCalledWith('/api/health', {
      credentials: 'include',
      headers: { Authorization: 'Bearer owner-secret' },
    })

    mockResponseOnce(401, 'denied')
    const err = await apiPost('/api/private', {}).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(401)
    expect((err as ApiError).friendly).toBe('需要访问令牌')
    expect((err as ApiError).raw).toContain('401: denied')
  })

  it('exchanges the token for an encoded websocket ticket', async () => {
    setApiToken('owner-secret')
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ticket: 'signed ticket', expires_at: 1 }), { status: 200 }),
    )
    await expect(authenticatedWsUrl('/ws/quotes')).resolves.toContain(
      '/ws/quotes?ticket=signed%20ticket',
    )
  })

  it('discovers local no-auth mode without storing a credential', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ mode: 'none', authenticated: true }), { status: 200 }),
    )

    await expect(loadAuthStatus()).resolves.toEqual({ mode: 'none', authenticated: true })
    expect(authMode.value).toBe('none')
    expect(authRequired.value).toBe(false)
    expect(getApiToken()).toBe('')
  })

  it('discovers pairing mode and sets authRequired when unauthenticated', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ mode: 'pairing', authenticated: false }), { status: 200 }),
    )

    await expect(loadAuthStatus()).resolves.toEqual({ mode: 'pairing', authenticated: false })
    expect(authMode.value).toBe('pairing')
    expect(authRequired.value).toBe(true)
  })

  it('clears authRequired when authenticated in pairing mode', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ mode: 'pairing', authenticated: true }), { status: 200 }),
    )

    await expect(loadAuthStatus()).resolves.toEqual({ mode: 'pairing', authenticated: true })
    expect(authMode.value).toBe('pairing')
    expect(authRequired.value).toBe(false)
  })
})

describe('ApiError mapping', () => {
  beforeEach(() => {
    sessionStorage.clear()
    authRequired.value = false
    vi.stubGlobal('fetch', vi.fn())
  })

  it.each<[number, string]>([
    [401, '需要访问令牌'],
    [403, '没有访问权限'],
    [404, '没有找到'],
    [500, '服务暂时不可用'],
    [502, '服务暂时不可用'],
    [503, '服务暂时不可用'],
    [400, '请求失败'],
    [418, '请求失败'],
  ])('maps HTTP %i to friendly "%s"', async (status, friendly) => {
    mockResponseOnce(status, '{"detail":"boom"}')
    const err = await apiGet('/api/whatever').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(status)
    expect((err as ApiError).friendly).toBe(friendly)
    // raw 保留技术细节（进 console），friendly 不含路径/JSON
    expect((err as ApiError).raw).toContain('/api/whatever')
    expect((err as ApiError).raw).toContain(String(status))
    expect((err as ApiError).friendly).not.toContain('/api/')
    expect((err as ApiError).friendly).not.toContain('{')
    // message 用 friendly，保证旧的 e.message 用法也只显示人话
    expect((err as ApiError).message).toBe(friendly)
  })

  it('maps network failure to status 0 + 网络连接失败', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))
    const err = await apiGet('/api/whatever').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(0)
    expect((err as ApiError).friendly).toBe('网络连接失败')
    expect((err as ApiError).raw).toContain('Failed to fetch')
  })

  it('rethrows abort errors untouched', async () => {
    const abort = new DOMException('The operation was aborted', 'AbortError')
    vi.mocked(fetch).mockRejectedValueOnce(abort)
    await expect(apiPost('/api/agent/route', {})).rejects.toBe(abort)
  })

  it('apiDelete also throws ApiError on failure', async () => {
    mockResponseOnce(500, 'boom')
    const err = await apiDelete('/api/x/1').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).friendly).toBe('服务暂时不可用')
  })

  it('toApiError passes ApiError through and wraps unknown errors', () => {
    const original = new ApiError(404, '没有找到', 'GET /api/x → 404')
    expect(toApiError(original)).toBe(original)

    const wrapped = toApiError(new TypeError('Failed to fetch'))
    expect(wrapped.status).toBe(0)
    expect(wrapped.friendly).toBe('网络连接失败')

    const fallback = toApiError(new Error('strange'))
    expect(fallback.status).toBe(0)
    expect(fallback.friendly).toBe('请求失败')
  })
})

describe('authRequired flag', () => {
  beforeEach(() => {
    sessionStorage.clear()
    authRequired.value = false
    vi.stubGlobal('fetch', vi.fn())
  })

  it('is set on 401 and cleared by the next successful request', async () => {
    expect(authRequired.value).toBe(false)

    mockResponseOnce(401, 'denied')
    await apiGet('/api/private').catch(() => undefined)
    expect(authRequired.value).toBe(true)

    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    )
    await apiGet('/api/health')
    expect(authRequired.value).toBe(false)
  })

  it('is not set by non-401 failures', async () => {
    mockResponseOnce(500, 'boom')
    await apiGet('/api/x').catch(() => undefined)
    expect(authRequired.value).toBe(false)
  })
})
