import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PortfolioSummary, PositionDetail, Adjustment } from '../api/types'
import { apiGet, apiPost, apiDelete } from '../api/client'

export interface AddPositionData {
  code: string
  name?: string
  buy_price: string
  shares: number
  buy_date?: string
  note?: string
}

export interface AddAdjustmentData {
  action: 'buy' | 'sell' | 'dividend'
  price: string
  shares: number
  note?: string
}

export const usePortfolioStore = defineStore('portfolio', () => {
  const summary = ref<PortfolioSummary | null>(null)
  const positions = ref<PositionDetail[]>([])
  const loading = ref(false)
  const lastFetch = ref(0)
  /** positionId → 调仓记录缓存 */
  const adjustmentsMap = ref<Record<number, Adjustment[]>>({})

  async function fetchSummary() {
    try {
      summary.value = await apiGet<PortfolioSummary>('/api/portfolio')
      positions.value = summary.value?.positions ?? []
      lastFetch.value = Date.now()
    } catch {
      summary.value = null
      positions.value = []
    }
  }

  async function fetchAll() {
    loading.value = true
    await fetchSummary()
    loading.value = false
  }

  async function addPosition(data: AddPositionData) {
    await apiPost('/api/portfolio/positions', data)
    await fetchAll()
  }

  async function removePosition(id: number) {
    await apiDelete(`/api/portfolio/positions/${id}`)
    delete adjustmentsMap.value[id]
    await fetchAll()
  }

  async function fetchAdjustments(positionId: number) {
    try {
      adjustmentsMap.value[positionId] = await apiGet<Adjustment[]>(
        `/api/portfolio/positions/${positionId}/adjustments`,
      )
    } catch {
      adjustmentsMap.value[positionId] = []
    }
  }

  async function addAdjustment(positionId: number, data: AddAdjustmentData) {
    await apiPost(`/api/portfolio/positions/${positionId}/adjustments`, data)
    await Promise.all([fetchAll(), fetchAdjustments(positionId)])
  }

  const totalPnl = computed(() => summary.value?.total_unrealized_pnl ?? null)
  const hasPositions = computed(() => positions.value.length > 0)
  const needsRefresh = computed(() => Date.now() - lastFetch.value > 30_000)

  return {
    summary,
    positions,
    loading,
    adjustmentsMap,
    totalPnl,
    hasPositions,
    needsRefresh,
    fetchSummary,
    fetchAll,
    addPosition,
    removePosition,
    fetchAdjustments,
    addAdjustment,
  }
})
