import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  apiGet,
  apiPost,
  authenticatedWsUrl,
  getApiToken,
  getChatSessionId,
  setApiToken,
} from './client'

describe('authenticated API state', () => {
  beforeEach(() => {
    sessionStorage.clear()
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
      headers: { Authorization: 'Bearer owner-secret' },
    })

    vi.mocked(fetch).mockResolvedValueOnce(new Response('denied', { status: 401 }))
    await expect(apiPost('/api/private', {})).rejects.toThrow('401: denied')
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
})
