// 主题 composable — 深色/浅色模式切换

import { ref, watch } from 'vue'

type Mode = 'light' | 'dark'

const STORAGE_KEY = 'mommy_theme'
const currentMode = ref<Mode>('light')

// 初始化时从 localStorage 读
if (typeof window !== 'undefined') {
  const saved = localStorage.getItem(STORAGE_KEY) as Mode | null
  if (saved === 'dark' || saved === 'light') {
    currentMode.value = saved
  } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    currentMode.value = 'dark'
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
    localStorage.setItem(STORAGE_KEY, mode)
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
