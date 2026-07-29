// 主题 composable — 深色/浅色模式切换
// 默认浅色（带微蓝调）—— 用户偏好近白背景，对比度更高

import { ref, watch } from 'vue'

type Mode = 'light' | 'dark'

const STORAGE_KEY = 'mommy_theme'
const STORAGE_VERSION = 3
const VERSION_KEY = 'mommy_theme_v'
const currentMode = ref<Mode>('light')

// 初始化：版本不匹配 → 强制 light；否则尊重显式存过的偏好
if (typeof window !== 'undefined') {
  const savedVersion = Number(localStorage.getItem(VERSION_KEY) || 0)
  const saved = localStorage.getItem(STORAGE_KEY) as Mode | null
  if (savedVersion < STORAGE_VERSION) {
    currentMode.value = 'light'
    try {
      localStorage.setItem(STORAGE_KEY, 'light')
      localStorage.setItem(VERSION_KEY, String(STORAGE_VERSION))
    } catch {
      /* ignore */
    }
  } else if (saved === 'dark' || saved === 'light') {
    currentMode.value = saved
  }
  applyMode(currentMode.value)
}

function applyMode(mode: Mode) {
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('dark', mode === 'dark')
    document.documentElement.style.colorScheme = mode
  }
}

watch(currentMode, (mode) => {
  if (typeof window !== 'undefined') {
    try {
      localStorage.setItem(STORAGE_KEY, mode)
      localStorage.setItem(VERSION_KEY, String(STORAGE_VERSION))
    } catch {
      /* ignore */
    }
    applyMode(mode)
  }
})

export function useTheme() {
  function toggle() {
    currentMode.value = currentMode.value === 'dark' ? 'light' : 'dark'
  }

  function setMode(mode: Mode) {
    currentMode.value = mode
  }

  return {
    currentMode,
    toggle,
    setMode,
  }
}
