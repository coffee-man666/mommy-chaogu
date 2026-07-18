import { describe, expect, it } from 'vitest'

import { changeColor, fmtAge, fmtMoney, fmtPct, fmtPrice } from './index'

describe('market formatting', () => {
  it('formats prices, percentages, and money', () => {
    expect(fmtPrice('12.345')).toBe('12.35')
    expect(fmtPct('1.2')).toBe('+1.20%')
    expect(fmtPct('-1.2')).toBe('-1.20%')
    expect(fmtMoney('250000000', 'yi')).toBe('2.50亿')
    expect(fmtMoney(undefined)).toBe('-')
  })

  it('formats age boundaries and A-share colors', () => {
    expect(fmtAge(59)).toBe('59秒前')
    expect(fmtAge(60)).toBe('1分钟前')
    expect(fmtAge(3600)).toBe('1小时前')
    expect(fmtAge(86400)).toBe('1天前')
    expect(changeColor('1')).toBe('#c83e3e')
    expect(changeColor('-1')).toBe('#2d8e3d')
    expect(changeColor('bad')).toBe('#666')
  })
})
