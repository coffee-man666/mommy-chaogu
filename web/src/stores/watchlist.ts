import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { WatchlistStock, WatchlistGroup } from '../api/types'
import { apiGet, apiPost, apiDelete } from '../api/client'

export const useWatchlistStore = defineStore('watchlist', () => {
  const entries = ref<WatchlistStock[]>([])
  const groups = ref<WatchlistGroup[]>([])
  const loading = ref(false)

  async function fetchAll() {
    loading.value = true
    try {
      const [e, g] = await Promise.all([
        apiGet<WatchlistStock[]>('/api/watchlist').catch(() => []),
        apiGet<WatchlistGroup[]>('/api/watchlist/groups').catch(() => []),
      ])
      entries.value = e
      groups.value = g
    } finally {
      loading.value = false
    }
  }

  async function addStock(code: string, group: string, note?: string) {
    await apiPost('/api/watchlist/stocks', { code, group, note })
    await fetchAll()
  }

  async function removeStock(code: string) {
    await apiDelete(`/api/watchlist/stocks/${code}`)
    await fetchAll()
  }

  async function addGroup(name: string, description?: string) {
    await apiPost('/api/watchlist/groups', { name, description })
    await fetchAll()
  }

  async function removeGroup(name: string) {
    await apiDelete(`/api/watchlist/groups/${name}`)
    await fetchAll()
  }

  /** 按分组分组 */
  const entriesByGroup = computed(() => {
    const map = new Map<string, WatchlistStock[]>()
    for (const e of entries.value) {
      const g = e.group || '默认'
      if (!map.has(g)) map.set(g, [])
      map.get(g)!.push(e)
    }
    return map
  })

  /** 所有代码列表 */
  const allCodes = computed(() => entries.value.map((e) => e.code))

  return {
    entries,
    groups,
    loading,
    entriesByGroup,
    allCodes,
    fetchAll,
    addStock,
    removeStock,
    addGroup,
    removeGroup,
  }
})
