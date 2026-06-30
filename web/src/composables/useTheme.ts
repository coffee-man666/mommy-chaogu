// 主题 composable —— 管理当前主题，持久化到 localStorage

import { ref, watch } from 'vue'
import { THEMES, DEFAULT_THEME_ID, applyTheme, getThemeById, type Theme } from '../themes'

const STORAGE_KEY = 'mommy_theme_id'

const currentThemeId = ref<string>(DEFAULT_THEME_ID)

// 初始化时从 localStorage 读
const saved = typeof window !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
if (saved && THEMES.some(t => t.id === saved)) {
  currentThemeId.value = saved
}
// 应用初始主题
if (typeof window !== 'undefined') {
  applyTheme(getThemeById(currentThemeId.value))
}

// 持久化 & 应用
watch(currentThemeId, (newId) => {
  if (typeof window !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, newId)
    applyTheme(getThemeById(newId))
  }
})

export function useTheme() {
  function setTheme(id: string) {
    if (THEMES.some(t => t.id === id)) {
      currentThemeId.value = id
    }
  }

  return {
    themes: THEMES,
    currentThemeId,
    currentTheme: () => getThemeById(currentThemeId.value),
    setTheme,
  }
}