/** Setup wizard API — typed methods for /api/setup/* and /api/auth/pair. */

import { apiFetch, apiGet, apiPost } from './client'

// ---------- Types (mirror backend Pydantic schemas) ----------

export type SetupAuthMode = 'none' | 'token' | 'pairing'

export interface SetupWeixinStatus {
  connected: boolean
  online: boolean
}

export interface SetupStatus {
  auth_mode: SetupAuthMode
  llm_configured: boolean
  provider: string
  model: string
  weixin: SetupWeixinStatus
  data_ok: boolean
}

export interface SetupProvider {
  id: string
  label: string
  default_model: string
  env_key: string
}

export interface SetupResult {
  ok: boolean
  message: string
}

export type WeixinStatus =
  | 'waiting'
  | 'scanned'
  | 'verification_required'
  | 'connected'
  | 'already_connected'
  | 'expired'
  | 'error'

export interface WeixinStartResult {
  pairing_id: string
  qr_data_url: string
  expires_in_seconds: number
  status: WeixinStatus
  message: string
}

export interface WeixinPollResult {
  status: WeixinStatus
  message: string
  gateway_started: boolean
  gateway_online: boolean
}

// ---------- API methods ----------

export async function getSetupStatus(): Promise<SetupStatus> {
  return apiGet<SetupStatus>('/api/setup/status')
}

export async function getSetupProviders(): Promise<SetupProvider[]> {
  return apiGet<SetupProvider[]>('/api/setup/providers')
}

export async function validateProvider(
  provider: string,
  model: string,
  apiKey: string,
): Promise<SetupResult> {
  return apiPost<SetupResult>('/api/setup/validate', { provider, model, api_key: apiKey })
}

export async function saveProvider(
  provider: string,
  model: string,
  apiKey: string,
): Promise<SetupResult> {
  return apiPost<SetupResult>('/api/setup/save', { provider, model, api_key: apiKey })
}

export async function startWeixinPairing(): Promise<WeixinStartResult> {
  return apiPost<WeixinStartResult>('/api/setup/weixin/start', {})
}

export async function pollWeixinPairing(
  pairingId: string,
  verifyCode = '',
): Promise<WeixinPollResult> {
  return apiPost<WeixinPollResult>('/api/setup/weixin/poll', {
    pairing_id: pairingId,
    verify_code: verifyCode,
  })
}

export async function submitPairingCode(code: string): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/api/auth/pair', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  })
  const body = await res.json() as { ok?: boolean; message?: string }
  return {
    ok: res.ok && body.ok === true,
    message: body.message || (res.ok ? '配对成功' : '配对失败，请重试'),
  }
}
