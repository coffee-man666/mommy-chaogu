import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
}))

import { apiGet, apiPost, apiPut } from './client'
import {
  getPreferences,
  LEGACY_STYLE_KEY,
  resetPreferences,
  updatePreferences,
  type Preferences,
} from './preferences'

const FULL: Preferences = {
  style: 'balanced',
  holding_period: 'swing',
  drawdown_sensitivity: 'medium',
  notify_min_severity: 'warning',
  watched_rules: [],
  reminder_windows: [{ start: '09:30', end: '15:00' }],
  default_hold_days: 5,
  updated_at: '2026-08-01T12:00:00+00:00',
}

describe('preferences API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('loads preferences from the server', async () => {
    vi.mocked(apiGet).mockResolvedValueOnce(FULL)
    const prefs = await getPreferences()
    expect(apiGet).toHaveBeenCalledWith('/api/preferences')
    expect(prefs).toEqual(FULL)
    expect(apiPut).not.toHaveBeenCalled()
  })

  it('partially updates preferences via PUT', async () => {
    vi.mocked(apiPut).mockResolvedValueOnce({ ...FULL, style: 'aggressive' })
    await updatePreferences({ style: 'aggressive' })
    expect(apiPut).toHaveBeenCalledWith('/api/preferences', { style: 'aggressive' })
  })

  it('resets preferences via POST', async () => {
    vi.mocked(apiPost).mockResolvedValueOnce(FULL)
    await resetPreferences()
    expect(apiPost).toHaveBeenCalledWith('/api/preferences/reset', {})
  })

  it('migrates a valid legacy style once and removes the key', async () => {
    localStorage.setItem(LEGACY_STYLE_KEY, 'conservative')
    vi.mocked(apiPut).mockResolvedValueOnce({ ...FULL, style: 'conservative' })
    vi.mocked(apiGet).mockResolvedValue(FULL)

    await getPreferences()
    expect(apiPut).toHaveBeenCalledWith('/api/preferences', { style: 'conservative' })
    expect(localStorage.getItem(LEGACY_STYLE_KEY)).toBeNull()

    vi.mocked(apiPut).mockClear()
    await getPreferences()
    expect(apiPut).not.toHaveBeenCalled()
  })

  it('removes the legacy key even when migration fails', async () => {
    localStorage.setItem(LEGACY_STYLE_KEY, 'aggressive')
    vi.mocked(apiPut).mockRejectedValueOnce(new Error('network down'))
    vi.mocked(apiGet).mockResolvedValueOnce(FULL)

    const prefs = await getPreferences()
    expect(prefs).toEqual(FULL)
    expect(localStorage.getItem(LEGACY_STYLE_KEY)).toBeNull()
  })

  it('ignores an invalid legacy value but still removes the key', async () => {
    localStorage.setItem(LEGACY_STYLE_KEY, 'yolo')
    vi.mocked(apiGet).mockResolvedValueOnce(FULL)

    await getPreferences()
    expect(apiPut).not.toHaveBeenCalled()
    expect(localStorage.getItem(LEGACY_STYLE_KEY)).toBeNull()
  })
})
