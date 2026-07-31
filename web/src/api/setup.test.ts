import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getSetupStatus,
  getSetupProviders,
  validateProvider,
  saveProvider,
  startWeixinPairing,
  pollWeixinPairing,
  submitPairingCode,
} from './setup'

describe('setup API', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('getSetupStatus calls GET /api/setup/status', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({
        auth_mode: 'none',
        llm_configured: true,
        provider: 'deepseek',
        model: 'deepseek-chat',
        weixin: { connected: false, online: false },
        data_ok: true,
      }), { status: 200 }),
    )
    const result = await getSetupStatus()
    expect(result.llm_configured).toBe(true)
    expect(result.auth_mode).toBe('none')
    expect(fetch).toHaveBeenCalledWith(
      '/api/setup/status',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('getSetupProviders calls GET /api/setup/providers', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify([
        { id: 'deepseek', label: 'DeepSeek', default_model: 'deepseek-chat', env_key: 'DEEPSEEK_API_KEY' },
      ]), { status: 200 }),
    )
    const result = await getSetupProviders()
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('deepseek')
  })

  it('validateProvider calls POST /api/setup/validate', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, message: '连接成功' }), { status: 200 }),
    )
    const result = await validateProvider('deepseek', 'deepseek-chat', 'sk-test')
    expect(result.ok).toBe(true)
    const call = vi.mocked(fetch).mock.calls[0]
    expect(call?.[0]).toBe('/api/setup/validate')
    const body = JSON.parse(call?.[1]?.body as string)
    expect(body.api_key).toBe('sk-test')
  })

  it('saveProvider calls POST /api/setup/save', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, message: '保存成功' }), { status: 200 }),
    )
    const result = await saveProvider('deepseek', 'deepseek-chat', 'sk-test')
    expect(result.ok).toBe(true)
  })

  it('startWeixinPairing calls POST /api/setup/weixin/start', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({
        pairing_id: 'abc',
        qr_data_url: 'data:image/svg+xml;base64,xxx',
        expires_in_seconds: 480,
        status: 'waiting',
        message: '请扫码',
      }), { status: 200 }),
    )
    const result = await startWeixinPairing()
    expect(result.status).toBe('waiting')
    expect(result.pairing_id).toBe('abc')
  })

  it('pollWeixinPairing calls POST /api/setup/weixin/poll', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({
        status: 'connected',
        message: '成功',
        gateway_started: true,
        gateway_online: true,
      }), { status: 200 }),
    )
    const result = await pollWeixinPairing('pid-123', '456')
    expect(result.status).toBe('connected')
    expect(result.gateway_online).toBe(true)
    const call = vi.mocked(fetch).mock.calls[0]
    const body = JSON.parse(call?.[1]?.body as string)
    expect(body.verify_code).toBe('456')
  })

  it('submitPairingCode calls POST /api/auth/pair', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, message: '配对成功' }), { status: 200 }),
    )
    const result = await submitPairingCode('123456')
    expect(result.ok).toBe(true)
    const call = vi.mocked(fetch).mock.calls[0]
    expect(call?.[0]).toBe('/api/auth/pair')
    const body = JSON.parse(call?.[1]?.body as string)
    expect(body.code).toBe('123456')
  })

  it('submitPairingCode preserves the safe server message on a rejected code', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: false, message: '配对码无效或已过期，请重启服务获取新码' }), { status: 401 }),
    )
    const result = await submitPairingCode('000000')
    expect(result).toEqual({
      ok: false,
      message: '配对码无效或已过期，请重启服务获取新码',
    })
    expect(fetch).toHaveBeenCalledWith(
      '/api/auth/pair',
      expect.objectContaining({ credentials: 'include' }),
    )
  })
})
