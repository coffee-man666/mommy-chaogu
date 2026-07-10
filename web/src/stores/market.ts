import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { IndexQuote, SectorQuote } from '../api/types'
import { apiGet } from '../api/client'

export const useMarketStore = defineStore('market', () => {
  const indexes = ref<IndexQuote[]>([])
  const sectors = ref<SectorQuote[]>([])
  const lastUpdate = ref(0)

  async function fetchIndexes() {
    try {
      indexes.value = await apiGet<IndexQuote[]>('/api/market/indexes')
      lastUpdate.value = Date.now()
    } catch {
      /* keep old data */
    }
  }

  async function fetchSectors(limit = 20) {
    try {
      sectors.value = await apiGet<SectorQuote[]>(`/api/market/sectors?limit=${limit}`)
    } catch {
      /* keep old data */
    }
  }

  async function fetchAll() {
    await Promise.all([fetchIndexes(), fetchSectors()])
  }

  return {
    indexes,
    sectors,
    lastUpdate,
    fetchIndexes,
    fetchSectors,
    fetchAll,
  }
})
