<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useMarketStore } from '../../stores/market'
import { usePortfolioStore } from '../../stores/portfolio'
import { useWatchlistStore } from '../../stores/watchlist'
import { getGainers, getSectors } from '../../api/market'
import { apiGet } from '../../api/client'
import { fmtPrice, fmtPct, fmtWan, changeColor, pnlColor, pnlSign } from '../../utils/format'
import PriceText from '../../components/PriceText.vue'
import ChangePct from '../../components/ChangePct.vue'
import EmptyState from '../../components/EmptyState.vue'
import type { RankingQuote, SectorQuote, Signal } from '../../api/types'

const router = useRouter()
const marketStore = useMarketStore()
const portfolioStore = usePortfolioStore()
const watchlistStore = useWatchlistStore()

const gainers = ref<RankingQuote[]>([])
const topSectors = ref<SectorQuote[]>([])
const recentSignals = ref<Signal[]>([])
const dataAge = ref(0)

let refreshTimer: number | null = null
let ageTimer: number | null = null

async function loadAll() {
  await Promise.all([
    marketStore.fetchAll(),
    portfolioStore.fetchAll(),
    watchlistStore.fetchAll(),
    getGainers(10).then((d) => (gainers.value = d)).catch(() => {}),
    getSectors(10).then((d) => (topSectors.value = d)).catch(() => {}),
    apiGet<Signal[]>('/api/signals/recent').then((d) => (recentSignals.value = d.slice(0, 3))).catch(() => {}),
  ])
  dataAge.value = 0
}

onMounted(() => {
  loadAll()
  refreshTimer = window.setInterval(loadAll, 30_000)
  ageTimer = window.setInterval(() => dataAge.value++, 1000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (ageTimer) clearInterval(ageTimer)
})

const dataDescription = computed(() => {
  if (dataAge.value < 30) return '实时'
  if (dataAge.value < 120) return `${dataAge.value}秒前`
  return `${Math.floor(dataAge.value / 60)}分钟前`
})

function goDetail(code: string) {
  router.push({ name: 'detail', params: { code } })
}
</script>

<template>
  <div class="dashboard">
    <!-- 顶部指数卡片 -->
    <div class="index-row">
      <div
        v-for="idx in marketStore.indexes.slice(0, 6)"
        :key="idx.code"
        class="index-card"
      >
        <div class="index-name">{{ idx.name }}</div>
        <PriceText :value="idx.price" :change-pct="idx.change_pct" size="lg" />
        <ChangePct :value="idx.change_pct" />
      </div>
    </div>

    <!-- 主区域 grid -->
    <div class="dash-grid">
      <!-- 自选股快览 -->
      <div class="dash-card watchlist-card">
        <div class="card-header">
          <span>📋 自选股</span>
          <span class="data-age">{{ dataDescription }}</span>
        </div>
        <EmptyState
          v-if="watchlistStore.entries.length === 0"
          icon="📝"
          title="暂无自选股"
          hint="去设置页添加"
        />
        <div v-else class="stock-list">
          <div
            v-for="stock in watchlistStore.entries.slice(0, 8)"
            :key="stock.code"
            class="stock-row"
            @click="goDetail(stock.code)"
          >
            <span class="stock-code">{{ stock.code }}</span>
            <span class="stock-name">{{ stock.name }}</span>
            <span class="stock-group">{{ stock.group }}</span>
          </div>
          <div
            v-if="watchlistStore.entries.length > 8"
            class="more-link"
            @click="router.push('/market')"
          >
            还有 {{ watchlistStore.entries.length - 8 }} 只 →
          </div>
        </div>
      </div>

      <!-- 持仓总览 -->
      <div class="dash-card portfolio-card">
        <div class="card-header">
          <span>💰 持仓总览</span>
        </div>
        <EmptyState
          v-if="!portfolioStore.summary || portfolioStore.summary.n_positions === 0"
          icon="💹"
          title="暂无持仓"
        />
        <div v-else class="portfolio-overview">
          <div class="pnl-card">
            <div class="pnl-label">总市值</div>
            <div class="pnl-value">{{ fmtWan(portfolioStore.summary.total_market_value) }}</div>
          </div>
          <div class="pnl-card">
            <div class="pnl-label">浮动盈亏</div>
            <div class="pnl-value" :style="{ color: pnlColor(portfolioStore.summary.total_unrealized_pnl) }">
              {{ pnlSign(portfolioStore.summary.total_unrealized_pnl) }}{{ fmtWan(portfolioStore.summary.total_unrealized_pnl) }}
            </div>
          </div>
          <div class="pnl-card">
            <div class="pnl-label">盈亏率</div>
            <div class="pnl-value" :style="{ color: pnlColor(portfolioStore.summary.total_unrealized_pnl_pct) }">
              {{ fmtPct(portfolioStore.summary.total_unrealized_pnl_pct) }}
            </div>
          </div>
        </div>
      </div>

      <!-- AI 对话入口 -->
      <div class="dash-card ai-card" @click="router.push('/agent')">
        <div class="card-header">
          <span>🤖 AI 助手</span>
        </div>
        <div class="ai-quick">
          <button class="quick-btn" @click.stop="router.push('/agent')">今天怎么样？</button>
          <button class="quick-btn" @click.stop="router.push('/agent')">持仓分析</button>
          <button class="quick-btn" @click.stop="router.push('/agent')">主力在买什么？</button>
        </div>
      </div>

      <!-- 板块排行 -->
      <div class="dash-card sector-card">
        <div class="card-header">
          <span>🔥 板块涨幅</span>
        </div>
        <EmptyState v-if="topSectors.length === 0" icon="📊" title="暂无数据" />
        <div v-else class="sector-list">
          <div
            v-for="(s, i) in topSectors.slice(0, 8)"
            :key="s.code"
            class="sector-row"
          >
            <span class="sector-rank">{{ i + 1 }}</span>
            <span class="sector-name">{{ s.name }}</span>
            <div class="sector-bar-container">
              <div
                class="sector-bar"
                :style="{
                  width: `${Math.min(Math.abs(Number(s.change_pct)) * 20, 100)}%`,
                  background: changeColor(s.change_pct),
                }"
              />
            </div>
            <ChangePct :value="s.change_pct" />
          </div>
        </div>
      </div>

      <!-- 最近信号 -->
      <div class="dash-card signal-card">
        <div class="card-header">
          <span>🔔 最近信号</span>
        </div>
        <EmptyState v-if="recentSignals.length === 0" icon="🔕" title="暂无信号" />
        <div v-else class="signal-list">
          <div
            v-for="sig in recentSignals"
            :key="sig.timestamp + sig.code"
            class="signal-row"
            @click="sig.code && /^\d{6}$/.test(sig.code) && goDetail(sig.code)"
          >
            <span
              class="signal-sev"
              :class="sig.severity"
            >{{ sig.severity === 'critical' ? '🔴' : sig.severity === 'warning' ? '🟡' : '🔵' }}</span>
            <span class="signal-title">{{ sig.title }}</span>
            <span v-if="sig.name" class="signal-name">{{ sig.name }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  padding: 16px;
  max-width: 1200px;
  margin: 0 auto;
}

/* 指数行 */
.index-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.index-card {
  background: var(--color-surface, #fff);
  border-radius: 12px;
  padding: 14px 16px;
  border: 1px solid var(--color-border, #eee);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.index-name {
  font-size: 13px;
  color: #888;
}

/* 主区域 grid */
.dash-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  grid-template-rows: auto auto;
  gap: 12px;
}
.watchlist-card { grid-column: 1; grid-row: 1 / 3; }
.portfolio-card { grid-column: 2; grid-row: 1; }
.ai-card { grid-column: 3; grid-row: 1; }
.sector-card { grid-column: 2 / 4; grid-row: 2; }
.signal-card { display: none; } /* 在窄屏隐藏 */

@media (min-width: 1024px) {
  .signal-card {
    display: block;
    grid-column: 3;
    grid-row: 2;
  }
  .sector-card { grid-column: 2; }
}

.dash-card {
  background: var(--color-surface, #fff);
  border-radius: 12px;
  padding: 16px;
  border: 1px solid var(--color-border, #eee);
  min-height: 120px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: #555;
}
.data-age {
  font-size: 11px;
  color: #aaa;
  font-weight: 400;
}

/* 自选股列表 */
.stock-list, .sector-list, .signal-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.stock-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.stock-row:hover {
  background: var(--color-bg, #f5f5f5);
}
.stock-code {
  font-family: 'SF Mono', monospace;
  font-size: 12px;
  color: #888;
  width: 54px;
}
.stock-name {
  flex: 1;
  color: #333;
}
.stock-group {
  font-size: 11px;
  color: #aaa;
  background: var(--color-bg, #f5f5f5);
  padding: 1px 6px;
  border-radius: 4px;
}
.more-link {
  font-size: 12px;
  color: var(--color-primary);
  text-align: center;
  padding: 6px;
  cursor: pointer;
}

/* 持仓概览 */
.portfolio-overview {
  display: flex;
  gap: 16px;
}
.pnl-card {
  flex: 1;
  text-align: center;
}
.pnl-label {
  font-size: 12px;
  color: #888;
  margin-bottom: 4px;
}
.pnl-value {
  font-size: 18px;
  font-weight: 700;
}

/* AI 卡片 */
.ai-card {
  cursor: pointer;
  transition: box-shadow 0.15s;
}
.ai-card:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}
.ai-quick {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.quick-btn {
  text-align: left;
  padding: 8px 12px;
  border: 1px solid var(--color-border, #eee);
  border-radius: 8px;
  background: var(--color-bg, #f9f9f9);
  color: #555;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.quick-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* 板块排行 */
.sector-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
}
.sector-rank {
  width: 20px;
  text-align: center;
  font-weight: 700;
  color: #aaa;
}
.sector-name {
  width: 80px;
  color: #333;
}
.sector-bar-container {
  flex: 1;
  height: 8px;
  background: #f0f0f0;
  border-radius: 4px;
  overflow: hidden;
}
.sector-bar {
  height: 100%;
  border-radius: 4px;
}

/* 信号 */
.signal-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  font-size: 13px;
  cursor: pointer;
}
.signal-sev { font-size: 12px; }
.signal-title { flex: 1; color: #555; }
.signal-name { font-size: 12px; color: #888; }
</style>
