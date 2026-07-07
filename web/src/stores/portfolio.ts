import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PortfolioSummary, PositionDetail, Adjustment } from '../api/types'
import { apiGet, apiPost, apiDelete } from '../api/client'

export const usePortfolioStore = defineStore('portfolio', () => {
  const summary = ref<PortfolioSummary | null>(null)
  const positions = ref<PositionDetail[]>([])
  const loading = ref(false)
  const lastFetch = ref(0)

  async function fetchSummary() {
    try {
      summary.value = await apiGet<PortfolioSummary>('/api/portfolio')
      lastFetch.value = Date.now()
    } catch {
      summary.value = null
    }
  }

  async function fetchPositions() {
    try {
      positions.value = summary.value?.positions ?? []
    } catch {
      positions.value = []
    }
  }

  async function fetchAll() {
    loading.value = true
    await Promise.all([fetchSummary(), fetchPositions()])
    loading.value = false
  }

  async function addPosition(data: {
    code: string
    name: string
    entry_price: string
    shares: number
    entry_date: string
    note?: string
  }) {
    await apiPost('/api/portfolio/positions', data)
    await fetchAll()
  }

  async function removePosition(id: number) {
    await apiDelete(`/api/portfolio/positions/${id}`)
    await fetchAll()
  }

  async function addAdjustment(
    positionId: number,
    data: { type: string; price: string; shares: number; date: string; note?: string }
  ) {
    await apiPost(`/api/portfolio/positions/${positionId}/adjustments`, data)
    await fetchAll()
  }

  async function getAdjustments(positionId: number): Promise<Adjustment[]> {
    return apiGet(`/api/portfolio/positions/${positionId}/adjustments`)
  }

  const totalPnl = computed(() => summary.value?.total_unrealized_pnl ?? null)
  const hasPositions = computed(() => positions.value.length > 0)
  const needsRefresh = computed(() => Date.now() - lastFetch.value > 30_000)

  return {
    summary,
    positions,
    loading,
    totalPnl,
    hasPositions,
    needsRefresh,
    fetchSummary,
    fetchPositions,
    fetchAll,
    addPosition,
    removePosition,
    addAdjustment,
    getAdjustments,
  }
})
