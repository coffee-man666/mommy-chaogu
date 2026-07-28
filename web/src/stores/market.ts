import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { IndexQuote, SectorQuote } from '../api/types'
import { apiGet, toApiError, type ApiError } from '../api/client'

export const useMarketStore = defineStore('market', () => {
  const indexes = ref<IndexQuote[]>([])
  const sectors = ref<SectorQuote[]>([])
  /** 最近一次拉取失败的原因；成功时清空。失败时保留旧数据 */
  const error = ref<ApiError | null>(null)
  const lastUpdate = ref(0)

  async function fetchIndexes() {
    try {
      indexes.value = await apiGet<IndexQuote[]>('/api/market/indexes')
      lastUpdate.value = Date.now()
      error.value = null
    } catch (e) {
      /* keep old data */
      error.value = toApiError(e)
    }
  }

  async function fetchSectors(limit = 20) {
    try {
      sectors.value = await apiGet<SectorQuote[]>(`/api/market/sectors?limit=${limit}`)
      error.value = null
    } catch (e) {
      /* keep old data */
      error.value = toApiError(e)
    }
  }

  async function fetchAll() {
    await Promise.all([fetchIndexes(), fetchSectors()])
  }

  return {
    indexes,
    sectors,
    error,
    lastUpdate,
    fetchIndexes,
    fetchSectors,
    fetchAll,
  }
})
