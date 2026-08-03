import { describe, expect, it } from 'vitest'

import { coverageBadgeLabels, fmtCountdown, verifyFreshnessText } from './predictionEvidence'

describe('fmtCountdown', () => {
  it('formats future times as a countdown', () => {
    expect(fmtCountdown(new Date(Date.now() + 2.5 * 86_400_000).toISOString())).toBe('2天后')
    expect(fmtCountdown(new Date(Date.now() + 3.5 * 3_600_000).toISOString())).toBe('3小时后')
    expect(fmtCountdown(new Date(Date.now() + 10.5 * 60_000).toISOString())).toBe('10分钟后')
  })

  it('reports past times as expired', () => {
    expect(fmtCountdown(new Date(Date.now() - 1000).toISOString())).toBe('已到期')
  })

  it('tolerates garbage input', () => {
    expect(fmtCountdown('not-a-date')).toBe('-')
  })
})

describe('coverageBadgeLabels', () => {
  it('maps known truthy keys to Chinese labels', () => {
    expect(
      coverageBadgeLabels(
        JSON.stringify({ quote: true, kline: true, flow_today: true, flow_5d: true, news: false }),
      ),
    ).toEqual(['行情', 'K线', '当日资金流', '5日资金流'])
  })

  it('deduplicates aliases and keeps unknown truthy keys verbatim', () => {
    expect(
      coverageBadgeLabels(JSON.stringify({ bars: true, kline: true, magic: 1 })),
    ).toEqual(['K线', 'magic'])
  })

  it('returns null for null, invalid JSON, or non-object payloads', () => {
    expect(coverageBadgeLabels(null)).toBeNull()
    expect(coverageBadgeLabels('{')).toBeNull()
    expect(coverageBadgeLabels('[1,2]')).toBeNull()
    expect(coverageBadgeLabels('"quote"')).toBeNull()
  })
})

describe('verifyFreshnessText', () => {
  it('describes the new shape with source and quote age', () => {
    expect(
      verifyFreshnessText(JSON.stringify({ quote: true, quote_age_seconds: 12, source: 'live' })),
    ).toBe('验证数据：实时报价 · 报价年龄 12s')
    expect(verifyFreshnessText(JSON.stringify({ quote: true, source: 'adapter' }))).toBe(
      '验证数据：实时报价',
    )
    expect(verifyFreshnessText(JSON.stringify({ quote: true, source: 'stale_cache' }))).toBe(
      '验证数据：缓存报价',
    )
    expect(verifyFreshnessText(JSON.stringify({ quote: true, source: 'cache' }))).toBe(
      '验证数据：缓存报价',
    )
  })

  it('falls back to quote availability for the old shape', () => {
    expect(verifyFreshnessText(JSON.stringify({ quote: true }))).toBe('验证数据：报价可用')
    expect(verifyFreshnessText(JSON.stringify({ quote: false }))).toBe('验证数据：报价不可用')
  })

  it('returns 未记录 for null, invalid JSON, or empty objects', () => {
    expect(verifyFreshnessText(null)).toBe('未记录')
    expect(verifyFreshnessText('oops')).toBe('未记录')
    expect(verifyFreshnessText('{}')).toBe('未记录')
  })
})
