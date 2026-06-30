// 语音识别 composable
// 浏览器原生 webkitSpeechRecognition，中文 → 解析为持仓表单字段

/* eslint-disable @typescript-eslint/no-explicit-any */

import { ref } from 'vue'

type RecognitionState = 'idle' | 'listening' | 'done' | 'error'

interface ParsedResult {
  code?: string
  name?: string
  price?: string
  shares?: string
  raw: string
}

// A 股代码正则：6位数字，0/3/6 开头
const CODE_RE = /(?:代码)?\b([036]\d{5})\b/

// 股数：数字 + 股/手
const SHARES_RE = /(\d+)\s*(?:股|手|股的)/

// 价格：数字（含小数），关键词 买/卖/价/成本
const PRICE_RE = /(?:买入|买|价格|成本|单价|价位)?[：:]?\s*(\d{3,5}(?:\.\d{1,3})?)\s*(?:元|块钱|块)?/

// 股票名称：常见中文（2-4字，后跟"买入"/"卖出"/"股"等关键词）
const NAME_RE = /([\u4e00-\u9fa5]{2,5})\s*(?:买入|卖出|成本|股|手)/

export function useSpeechRecognition() {
  const state = ref<RecognitionState>('idle')
  const transcript = ref('')
  const error = ref('')
  let recognition: any = null

  function isSupported(): boolean {
    return typeof window !== 'undefined' &&
      ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)
  }

  function getRecognition(): any {
    if (!isSupported()) return null
    if (recognition) return recognition

    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    recognition = new SR()
    recognition.lang = 'zh-CN'
    recognition.continuous = false
    recognition.interimResults = true
    recognition.maxAlternatives = 3

    recognition.onresult = (event: any) => {
      let text = ''
      for (let i = 0; i < event.results.length; i++) {
        text += event.results[i][0].transcript
      }
      transcript.value = text
    }

    recognition.onerror = (event: any) => {
      state.value = 'error'
      error.value = event.error || '识别失败'
      if (event.error === 'no-speech') {
        error.value = '没听到，再说一次'
      } else if (event.error === 'not-allowed') {
        error.value = '请允许麦克风权限'
      }
    }

    recognition.onend = () => {
      if (state.value === 'listening') {
        state.value = 'done'
      }
    }

    return recognition
  }

  function start() {
    const r = getRecognition()
    if (!r) {
      error.value = '浏览器不支持语音'
      state.value = 'error'
      return
    }
    transcript.value = ''
    error.value = ''
    state.value = 'listening'
    try {
      r.start()
    } catch {
      // 可能重复 start
      r.stop()
      setTimeout(() => r.start(), 200)
    }
  }

  function stop() {
    const r = getRecognition()
    if (r && state.value === 'listening') {
      try { r.stop() } catch { /* ignore */ }
    }
    state.value = 'idle'
  }

  function parse(text: string): ParsedResult {
    const result: ParsedResult = { raw: text }

    // 代码
    const codeMatch = text.match(CODE_RE)
    if (codeMatch) {
      result.code = codeMatch[1]
    }

    // 股数
    const sharesMatch = text.match(SHARES_RE)
    if (sharesMatch) {
      result.shares = sharesMatch[1]
    }

    // 名称
    const nameMatch = text.match(NAME_RE)
    if (nameMatch) {
      result.name = nameMatch[1]
    }

    // 价格 — 尽量取跟在"买入/成本/价"后面的数字
    // 先尝试带关键词的
    const pricedKw = text.match(/(?:买入|买|成本|单价|价|元)[价是]?\s*[:：]?\s*(\d{2,5}(?:\.\d{1,3})?)/)
    if (pricedKw) {
      result.price = pricedKw[1]
    } else {
      // fallback：找小数点数字（股价大概率有小数）
      const decimalNum = text.match(/(\d{2,5}\.\d{1,3})/)
      if (decimalNum) {
        result.price = decimalNum[1]
      }
    }

    // 如果没有股数但有价格，尝试从剩余数字找股数
    if (!result.shares) {
      // 去掉已匹配的代码和价格，剩下的纯整数可能是股数
      let remaining = text
      if (result.code) remaining = remaining.replace(result.code, '')
      if (result.price) remaining = remaining.replace(result.price, '')
      const nums = remaining.match(/(\d{2,6})/)
      if (nums) {
        result.shares = nums[1]
      }
    }

    return result
  }

  return {
    state,
    transcript,
    error,
    isSupported,
    start,
    stop,
    parse,
  }
}
