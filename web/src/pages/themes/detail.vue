<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { apiGet } from '../../api/client'
import { fmtPrice, fmtPct, fmtWan, changeColor } from '../../utils/format'
import ChangePct from '../../components/ChangePct.vue'
import PriceText from '../../components/PriceText.vue'
import EmptyState from '../../components/EmptyState.vue'
import LoadingSpinner from '../../components/LoadingSpinner.vue'

interface ThemeStock {
  code: string
  name: string
  price: string
  change_pct: string
  volume: number
  turnover_rate: string | null
  pe: string | null
  main_net_inflow: string | null
  subcategory: string
  level: string
  role: string
  growth_text: string
  growth_low: number | null
  growth_high: number | null
  core_driver: string
  highlight: string
  error?: string
}

interface ThemeDetail {
  id: string
  name: string
  description: string
  total_stocks: number
  subcategories: string[]
  stocks: any[]
}

const router = useRouter()
const route = useRoute()
const themeId = computed(() => route.params.id as string)

const theme = ref<ThemeDetail | null>(null)
const stocks = ref<ThemeStock[]>([])
const loading = ref(true)
const loadingQuotes = ref(false)
const activeSub = ref('')
const sortBy = ref<'change' | 'main_net' | 'growth'>('change')
const sortDir = ref<'desc' | 'asc'>('desc')

const themeIcons: Record<string, string> = {
  semiconductor: '🔧',
  innovative_drug: '💊',
  humanoid_robot: '🤖',
  materials: '🧱',
  earnings_watch: '📊',
}

async function loadTheme() {
  loading.value = true
  try {
    const data = await apiGet<ThemeDetail>(`/api/themes/${themeId.value}`)
    theme.value = data
  } catch {
    theme.value = null
  } finally {
    loading.value = false
  }
  await loadQuotes()
}

async function loadQuotes() {
  loadingQuotes.value = true
  try {
    const data = await apiGet<{ items: ThemeStock[]; total: number }>(
      `/api/themes/${themeId.value}/quotes?limit=200`
    )
    stocks.value = data.items
  } catch {
    stocks.value = []
  } finally {
    loadingQuotes.value = false
  }
}

onMounted(loadTheme)
watch(themeId, loadTheme)

const isEarnings = computed(() => themeId.value === 'earnings_watch')

const subcategories = computed(() => {
  if (!theme.value?.subcategories?.length) return []
  return ['全部', ...theme.value.subcategories]
})

const filteredStocks = computed(() => {
  let result = stocks.value
  if (activeSub.value && activeSub.value !== '全部') {
    result = result.filter(
      (s) => s.subcategory === activeSub.value || s.level === activeSub.value
    )
  }
  // sort
  result = [...result].sort((a, b) => {
    let av = 0
    let bv = 0
    if (sortBy.value === 'change') {
      av = Number(a.change_pct) || 0
      bv = Number(b.change_pct) || 0
    } else if (sortBy.value === 'main_net') {
      av = Number(a.main_net_inflow) || 0
      bv = Number(b.main_net_inflow) || 0
    } else if (sortBy.value === 'growth') {
      av = a.growth_low ?? 0
      bv = b.growth_low ?? 0
    }
    return sortDir.value === 'desc' ? bv - av : av - bv
  })
  return result
})

const summary = computed(() => {
  const total = stocks.value.length
  if (total === 0) return null
  const up = stocks.value.filter((s) => Number(s.change_pct) > 0).length
  const down = stocks.value.filter((s) => Number(s.change_pct) < 0).length
  const flat = total - up - down
  const avgPct =
    stocks.value.reduce((sum, s) => sum + (Number(s.change_pct) || 0), 0) / total
  const totalMain = stocks.value.reduce(
    (sum, s) => sum + (Number(s.main_net_inflow) || 0),
    0
  )
  return { total, up, down, flat, avgPct, totalMain }
})

// 按 subcategory 分组统计
const subStats = computed(() => {
  const map = new Map<string, { count: number; avgPct: number; total: number }>()
  for (const s of stocks.value) {
    const key = s.subcategory || s.level || '其他'
    if (!map.has(key)) map.set(key, { count: 0, avgPct: 0, total: 0 })
    const e = map.get(key)!
    e.count++
    e.total += Number(s.change_pct) || 0
  }
  for (const [, v] of map) v.avgPct = v.total / v.count
  return Array.from(map.entries())
    .map(([name, stats]) => ({ name, ...stats }))
    .sort((a, b) => b.avgPct - a.avgPct)
})

function toggleSort(col: 'change' | 'main_net' | 'growth') {
  if (sortBy.value === col) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortBy.value = col
    sortDir.value = 'desc'
  }
}

function goDetail(code: string) {
  if (/^\d{6}$/.test(code)) router.push({ name: 'detail', params: { code } })
}
</script>

<template>
  <div class="theme-detail">
    <!-- Header -->
    <div class="theme-header">
      <div class="header-top">
        <span class="back-btn" @click="router.push('/themes')">← 主题</span>
      </div>
      <h2 class="theme-title">
        {{ themeIcons[themeId] || '📈' }} {{ theme?.name || '加载中...' }}
      </h2>
      <p v-if="theme" class="theme-desc">{{ theme.description }}</p>
    </div>

    <LoadingSpinner v-if="loading" />

    <template v-else-if="theme">
      <!-- 概览 -->
      <div v-if="summary" class="summary-bar">
        <div class="summary-item">
          <span class="label">总数</span>
          <span class="value">{{ summary.total }}</span>
        </div>
        <div class="summary-item">
          <span class="label">涨/跌/平</span>
          <span class="value">
            <span style="color: #c83e3e">{{ summary.up }}</span> /
            <span style="color: #2d8e3d">{{ summary.down }}</span> /
            {{ summary.flat }}
          </span>
        </div>
        <div class="summary-item">
          <span class="label">均价</span>
          <ChangePct :value="summary.avgPct.toFixed(2)" />
        </div>
        <div class="summary-item">
          <span class="label">主力合计</span>
          <span class="value" :style="{ color: changeColor(summary.totalMain) }">
            {{ fmtWan(summary.totalMain) }}
          </span>
        </div>
      </div>

      <!-- 子板块统计 -->
      <div v-if="subStats.length > 1" class="sub-stats">
        <div
          v-for="s in subStats"
          :key="s.name"
          class="sub-stat-chip"
          :class="{ active: activeSub === s.name }"
          @click="activeSub = activeSub === s.name ? '' : s.name"
        >
          <span class="chip-name">{{ s.name }}</span>
          <span class="chip-count">{{ s.count }}</span>
          <span class="chip-pct" :style="{ color: changeColor(s.avgPct) }">
            {{ s.avgPct >= 0 ? '+' : '' }}{{ s.avgPct.toFixed(2) }}%
          </span>
        </div>
      </div>

      <!-- 过滤标签 -->
      <div v-if="subcategories.length" class="filter-bar">
        <button
          v-for="sub in subcategories"
          :key="sub"
          class="filter-btn"
          :class="{ active: (activeSub || '全部') === sub }"
          @click="activeSub = sub === '全部' ? '' : sub"
        >
          {{ sub }}
        </button>
      </div>

      <!-- 股票表格 -->
      <div class="stock-table-wrap">
        <LoadingSpinner v-if="loadingQuotes" text="拉取行情中..." />
        <EmptyState
          v-else-if="filteredStocks.length === 0"
          icon="📭"
          title="暂无数据"
        />
        <table v-else class="stock-table">
          <thead>
            <tr>
              <th>代码/名称</th>
              <th class="sortable" @click="toggleSort('change')">
                涨跌{{ sortBy === 'change' ? (sortDir === 'desc' ? '↓' : '↑') : '' }}
              </th>
              <th class="sortable" @click="toggleSort('main_net')">
                主力{{ sortBy === 'main_net' ? (sortDir === 'desc' ? '↓' : '↑') : '' }}
              </th>
              <th v-if="isEarnings" class="sortable" @click="toggleSort('growth')">
                预期增速{{
                  sortBy === 'growth' ? (sortDir === 'desc' ? '↓' : '↑') : ''
                }}
              </th>
              <th>分类</th>
              <th>PE</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in filteredStocks"
              :key="s.code"
              class="stock-row"
              @click="goDetail(s.code)"
            >
              <td class="td-name">
                <div class="code-name">
                  <span class="s-code">{{ s.code }}</span>
                  <span class="s-name">{{ s.name }}</span>
                </div>
                <div v-if="s.role" class="s-role">{{ s.role }}</div>
                <div v-if="s.highlight" class="s-highlight">★ {{ s.highlight }}</div>
              </td>
              <td>
                <PriceText :value="s.price" :change-pct="s.change_pct" size="sm" />
                <div style="margin-top: 2px">
                  <ChangePct :value="s.change_pct" />
                </div>
              </td>
              <td>
                <span
                  v-if="s.main_net_inflow"
                  :style="{ color: changeColor(s.main_net_inflow) }"
                >
                  {{ fmtWan(s.main_net_inflow) }}
                </span>
                <span v-else style="color: #ccc">-</span>
              </td>
              <td v-if="isEarnings">
                <span v-if="s.growth_text" class="growth-badge" :class="{
                  high: (s.growth_low ?? 0) >= 200,
                  mid: (s.growth_low ?? 0) >= 50 && (s.growth_low ?? 0) < 200,
                }">
                  {{ s.growth_text }}
                </span>
                <div v-if="s.core_driver" class="driver-tag">{{ s.core_driver }}</div>
              </td>
              <td>
                <span v-if="s.subcategory" class="cat-tag">{{ s.subcategory }}</span>
                <span v-else-if="s.level" class="cat-tag">{{ s.level }}</span>
              </td>
              <td>
                <span v-if="s.pe" style="font-size: 12px; color: #888">
                  {{ Number(s.pe).toFixed(1) }}
                </span>
                <span v-else style="color: #ccc">-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <EmptyState v-else icon="❌" title="主题不存在" hint="返回主题列表" />
  </div>
</template>

<style scoped>
.theme-detail {
  padding: 16px;
  max-width: 1000px;
  margin: 0 auto;
}

.back-btn {
  font-size: 14px;
  color: var(--color-primary, #c83e3e);
  cursor: pointer;
}

.theme-title {
  font-size: 20px;
  font-weight: 700;
  margin: 8px 0 4px;
}
.theme-desc {
  font-size: 13px;
  color: #888;
  line-height: 1.4;
  margin: 0 0 16px;
}

/* 概览栏 */
.summary-bar {
  display: flex;
  gap: 20px;
  padding: 14px 16px;
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #eee);
  border-radius: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.summary-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.summary-item .label {
  font-size: 11px;
  color: #999;
}
.summary-item .value {
  font-size: 15px;
  font-weight: 600;
}

/* 子板块统计 */
.sub-stats {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 8px 0;
  margin-bottom: 8px;
}
.sub-stat-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #eee);
  border-radius: 8px;
  cursor: pointer;
  white-space: nowrap;
  font-size: 12px;
  transition: border-color 0.15s;
}
.sub-stat-chip.active {
  border-color: var(--color-primary);
  background: var(--color-primary) 10;
}
.chip-name {
  font-weight: 600;
  color: #555;
}
.chip-count {
  color: #aaa;
}
.chip-pct {
  font-weight: 600;
}

/* 过滤栏 */
.filter-bar {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 8px;
}
.filter-btn {
  padding: 4px 12px;
  border: 1px solid var(--color-border, #eee);
  border-radius: 16px;
  background: transparent;
  color: #888;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}
.filter-btn.active {
  background: var(--color-primary, #c83e3e);
  color: white;
  border-color: var(--color-primary);
}

/* 表格 */
.stock-table-wrap {
  overflow-x: auto;
}
.stock-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.stock-table th {
  text-align: left;
  padding: 8px 10px;
  font-size: 11px;
  font-weight: 600;
  color: #999;
  border-bottom: 2px solid var(--color-border, #eee);
  white-space: nowrap;
}
.stock-table th.sortable {
  cursor: pointer;
  user-select: none;
}
.stock-table th.sortable:hover {
  color: var(--color-primary);
}
.stock-table td {
  padding: 10px;
  border-bottom: 1px solid #f0f0f0;
  vertical-align: top;
}
.stock-row {
  cursor: pointer;
  transition: background 0.1s;
}
.stock-row:hover {
  background: #fafafa;
}

.td-name .code-name {
  display: flex;
  gap: 6px;
  align-items: center;
}
.s-code {
  font-family: 'SF Mono', monospace;
  font-size: 11px;
  color: #888;
}
.s-name {
  font-weight: 600;
  color: #333;
}
.s-role {
  font-size: 11px;
  color: #aaa;
  margin-top: 2px;
}
.s-highlight {
  font-size: 11px;
  color: #d48806;
  margin-top: 2px;
}

.cat-tag {
  font-size: 11px;
  color: #666;
  background: #f5f5f5;
  padding: 1px 6px;
  border-radius: 4px;
}

.growth-badge {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}
.growth-badge.high {
  color: #c83e3e;
  background: rgba(200, 62, 62, 0.1);
}
.growth-badge.mid {
  color: #d48806;
  background: rgba(212, 136, 6, 0.1);
}
.driver-tag {
  font-size: 11px;
  color: #888;
  margin-top: 2px;
}

/* 移动端表格优化 */
@media (max-width: 767px) {
  .stock-table {
    font-size: 12px;
  }
  .stock-table th,
  .stock-table td {
    padding: 6px;
  }
}
</style>
