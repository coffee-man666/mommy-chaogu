<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getIndexes, getSectors, getGainers, getLosers } from '../../api/market'
import { getPortfolio } from '../../api/portfolio'
import { fmtPrice, fmtPct, changeColor } from '../../api'
import type { IndexQuote, SectorQuote, RankingQuote } from '../../api/types'
import type { PortfolioSummary } from '../../api/types'

const router = useRouter()

const indexes = ref<IndexQuote[]>([])
const sectors = ref<SectorQuote[]>([])
const gainers = ref<RankingQuote[]>([])
const losers = ref<RankingQuote[]>([])
const portfolio = ref<PortfolioSummary | null>(null)

const loading = ref(true)
const activeTab = ref<'gainers' | 'losers' | 'sectors'>('gainers')
const dataAge = ref(0)

let refreshTimer: number | null = null
let ageTimer: number | null = null

async function load() {
  try {
    const [idx, sec, g, l, pf] = await Promise.all([
      getIndexes().catch(() => []),
      getSectors(20).catch(() => []),
      getGainers(20).catch(() => []),
      getLosers(20).catch(() => []),
      getPortfolio().catch(() => null),
    ])
    indexes.value = idx
    sectors.value = sec
    gainers.value = g
    losers.value = l
    portfolio.value = pf
    dataAge.value = 0
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function goDetail(code: string) {
  router.push({ name: 'detail', params: { code } })
}

function indexColor(pct: string): string {
  const n = Number(pct)
  if (isNaN(n) || n === 0) return '#fff'
  return n >= 0 ? 'var(--color-primary)' : 'var(--color-down)'
}

function fmtFlowWan(s: string | null | undefined): string {
  if (!s) return '-'
  const n = Number(s)
  if (isNaN(n)) return s
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(0)
}

function pnlColor(pnl: string | null): string {
  if (!pnl) return '#999'
  return Number(pnl) >= 0 ? 'var(--color-primary)' : 'var(--color-down)'
}

function pnlSign(pnl: string | null): string {
  if (!pnl) return ''
  return Number(pnl) >= 0 ? '+' : ''
}

function fmtWan(s: string | null | undefined): string {
  if (!s) return '-'
  const n = Number(s)
  if (isNaN(n)) return s
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(2)
}

const dataDescription = computed(() => {
  if (dataAge.value < 30) return '实时'
  if (dataAge.value < 120) return `${dataAge.value}秒前`
  return `${Math.floor(dataAge.value / 60)}分钟前`
})

onMounted(() => {
  load()
  refreshTimer = window.setInterval(load, 30000)
  ageTimer = window.setInterval(() => dataAge.value++, 1000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (ageTimer) clearInterval(ageTimer)
})
</script>

<template>
  <div class="market-page">
    <!-- 顶部红色头部 -->
    <header class="header">
      <div class="header-top">
        <div class="title">📊 盘面</div>
        <div class="data-age">{{ dataDescription }} · 30秒刷新</div>
      </div>

      <!-- 持仓快览条 -->
      <div class="portfolio-bar" v-if="portfolio && portfolio.n_positions > 0" @click="router.push('/portfolio')">
        <div class="pb-left">
          <span class="pb-icon">💰</span>
          <span class="pb-label">持仓</span>
          <span class="pb-count">{{ portfolio.n_positions }}</span>
        </div>
        <div class="pb-right">
          <span class="pb-value">{{ fmtWan(portfolio.total_market_value) }}</span>
          <span class="pb-pnl" :style="{ color: pnlColor(portfolio.total_unrealized_pnl) }">
            {{ pnlSign(portfolio.total_unrealized_pnl) }}{{ fmtWan(portfolio.total_unrealized_pnl) }}
            ({{ fmtPct(portfolio.total_unrealized_pnl_pct || '0') }})
          </span>
          <span class="pb-arrow">›</span>
        </div>
      </div>
    </header>

    <!-- 大盘指数区 -->
    <section class="index-section">
      <div class="section-title">📈 大盘指数</div>
      <div class="index-grid">
        <div
          v-for="idx in indexes.slice(0, 4)"
          :key="idx.code"
          class="index-card"
          :style="{ background: indexColor(idx.change_pct) === '#fff' ? '#f0f0f0' : indexColor(idx.change_pct) + '20' }"
        >
          <div class="idx-name">{{ idx.name }}</div>
          <div class="idx-price">{{ fmtPrice(idx.price) }}</div>
          <div class="idx-pct" :style="{ color: indexColor(idx.change_pct) }">
            {{ fmtPct(idx.change_pct) }}
          </div>
        </div>
      </div>
      <div class="index-extra" v-if="indexes.length > 4">
        <div v-for="idx in indexes.slice(4)" :key="idx.code" class="idx-extra-row">
          <span class="idx-extra-name">{{ idx.name }}</span>
          <span class="idx-extra-price">{{ fmtPrice(idx.price) }}</span>
          <span class="idx-extra-pct" :style="{ color: indexColor(idx.change_pct) }">
            {{ fmtPct(idx.change_pct) }}
          </span>
        </div>
      </div>
    </section>

    <!-- Tab 切换：涨幅 / 跌幅 / 板块 -->
    <section class="rank-section">
      <div class="rank-tabs">
        <span :class="['rank-tab', { active: activeTab === 'gainers' }]" @click="activeTab = 'gainers'">
          🔥 涨幅榜
        </span>
        <span :class="['rank-tab', { active: activeTab === 'losers' }]" @click="activeTab = 'losers'">
          💧 跌幅榜
        </span>
        <span :class="['rank-tab', { active: activeTab === 'sectors' }]" @click="activeTab = 'sectors'">
          🏭 板块榜
        </span>
      </div>

      <!-- 涨幅榜 -->
      <div v-if="activeTab === 'gainers'" class="rank-list">
        <div class="rank-row rank-header">
          <span class="rk-rank">#</span>
          <span class="rk-name">名称</span>
          <span class="rk-price">最新</span>
          <span class="rk-pct">涨幅</span>
        </div>
        <div
          v-for="(item, i) in gainers"
          :key="item.code"
          class="rank-row"
          @click="goDetail(item.code)"
        >
          <span class="rk-rank" :class="{ top: i < 3 }">{{ i + 1 }}</span>
          <span class="rk-name">
            <span class="rk-stock-name">{{ item.name }}</span>
            <span class="rk-stock-code">{{ item.code }}</span>
          </span>
          <span class="rk-price">{{ fmtPrice(item.price) }}</span>
          <span class="rk-pct" :style="{ color: 'var(--color-primary)' }">{{ fmtPct(item.change_pct) }}</span>
        </div>
        <div v-if="!gainers.length" class="empty-mini">暂无数据</div>
      </div>

      <!-- 跌幅榜 -->
      <div v-else-if="activeTab === 'losers'" class="rank-list">
        <div class="rank-row rank-header">
          <span class="rk-rank">#</span>
          <span class="rk-name">名称</span>
          <span class="rk-price">最新</span>
          <span class="rk-pct">跌幅</span>
        </div>
        <div
          v-for="(item, i) in losers"
          :key="item.code"
          class="rank-row"
          @click="goDetail(item.code)"
        >
          <span class="rk-rank" :class="{ top: i < 3 }">{{ i + 1 }}</span>
          <span class="rk-name">
            <span class="rk-stock-name">{{ item.name }}</span>
            <span class="rk-stock-code">{{ item.code }}</span>
          </span>
          <span class="rk-price">{{ fmtPrice(item.price) }}</span>
          <span class="rk-pct" :style="{ color: 'var(--color-down)' }">{{ fmtPct(item.change_pct) }}</span>
        </div>
        <div v-if="!losers.length" class="empty-mini">暂无数据</div>
      </div>

      <!-- 板块榜 -->
      <div v-else class="rank-list">
        <div class="rank-row rank-header">
          <span class="rk-rank">#</span>
          <span class="rk-name">板块</span>
          <span class="rk-price">点位</span>
          <span class="rk-pct">涨幅</span>
        </div>
        <div
          v-for="(item, i) in sectors"
          :key="item.code"
          class="rank-row"
        >
          <span class="rk-rank" :class="{ top: i < 3 }">{{ i + 1 }}</span>
          <span class="rk-name">
            <span class="rk-stock-name">{{ item.name }}</span>
            <span class="rk-stock-code">{{ item.code }}</span>
          </span>
          <span class="rk-price">{{ fmtPrice(item.price) }}</span>
          <span class="rk-pct" :style="{ color: changeColor(item.change_pct) }">{{ fmtPct(item.change_pct) }}</span>
        </div>
        <div v-if="!sectors.length" class="empty-mini">暂无数据</div>
      </div>
    </section>

    <!-- 加载占位 -->
    <div v-if="loading" class="loading-box">
      <div class="loading-text">盘面加载中...</div>
    </div>
  </div>
</template>

<style scoped>
.market-page {
  min-height: 100vh;
  background: var(--color-bg);
  padding-bottom: 24px;
}

.header {
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-dark));
  color: white;
  padding: 18px 16px 0;
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
}

.title {
  font-size: 26px;
  font-weight: bold;
}

.data-age {
  font-size: 12px;
  opacity: 0.85;
  font-family: 'Courier New', monospace;
}

/* 持仓快览 */
.portfolio-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(255, 255, 255, 0.12);
  padding: 10px 12px;
  border-radius: 10px;
  margin-bottom: 12px;
  cursor: pointer;
}

.portfolio-bar:active { background: rgba(255, 255, 255, 0.2); }

.pb-left {
  display: flex;
  align-items: center;
  gap: 4px;
}

.pb-icon { font-size: 16px; }
.pb-label { font-size: 13px; }
.pb-count {
  background: rgba(255, 255, 255, 0.25);
  color: white;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 10px;
}

.pb-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pb-value {
  font-size: 14px;
  font-weight: 700;
  font-family: 'Courier New', monospace;
  color: white;
}

.pb-pnl {
  font-size: 13px;
  font-weight: 600;
  font-family: 'Courier New', monospace;
}

.pb-arrow {
  font-size: 18px;
  color: rgba(255, 255, 255, 0.6);
}

/* 大盘指数 */
.index-section {
  background: white;
  margin: 12px;
  padding: 14px;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.section-title {
  font-size: 15px;
  font-weight: 700;
  margin-bottom: 10px;
}

.index-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.index-card {
  padding: 10px;
  border-radius: 8px;
  text-align: left;
}

.idx-name {
  font-size: 12px;
  color: #666;
  margin-bottom: 2px;
}

.idx-price {
  font-size: 18px;
  font-weight: 700;
  font-family: 'Courier New', monospace;
  color: #333;
}

.idx-pct {
  font-size: 13px;
  font-weight: 700;
  font-family: 'Courier New', monospace;
  margin-top: 2px;
}

.index-extra {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #eee;
}

.idx-extra-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 4px 0;
}

.idx-extra-name { color: #666; }
.idx-extra-price { color: #333; font-family: 'Courier New', monospace; font-weight: 600; }
.idx-extra-pct { font-family: 'Courier New', monospace; font-weight: 700; min-width: 60px; text-align: right; }

/* 排行榜 */
.rank-section {
  background: white;
  margin: 12px;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  overflow: hidden;
}

.rank-tabs {
  display: flex;
  border-bottom: 1px solid #eee;
}

.rank-tab {
  flex: 1;
  text-align: center;
  padding: 12px 0;
  font-size: 13px;
  font-weight: 600;
  color: #666;
  cursor: pointer;
  user-select: none;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.rank-tab.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}

.rank-list {
  padding: 4px 0;
}

.rank-row {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  font-size: 13px;
  cursor: pointer;
  border-bottom: 1px solid var(--color-bg);
}

.rank-row:active { background: var(--color-bg); }

.rank-row.rank-header {
  color: #999;
  font-size: 11px;
  font-weight: 600;
  cursor: default;
  background: #f8f8f8;
}

.rank-row.rank-header:active { background: #f8f8f8; }

.rk-rank {
  width: 28px;
  font-family: 'Courier New', monospace;
  font-weight: 700;
  color: #999;
  font-size: 13px;
}

.rk-rank.top {
  color: var(--color-primary);
  background: var(--color-bg);
  border-radius: 50%;
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}

.rk-name {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  margin-left: 4px;
}

.rk-stock-name {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rk-stock-code {
  font-size: 10px;
  color: #aaa;
  margin-top: 1px;
}

.rk-price {
  width: 70px;
  text-align: right;
  font-family: 'Courier New', monospace;
  font-weight: 600;
  color: #333;
}

.rk-pct {
  width: 70px;
  text-align: right;
  font-family: 'Courier New', monospace;
  font-weight: 700;
  font-size: 14px;
}

.empty-mini {
  padding: 24px 0;
  text-align: center;
  color: #999;
  font-size: 13px;
}

.loading-box {
  padding: 40px 0;
  text-align: center;
}

.loading-text {
  color: #999;
  font-size: 13px;
}
</style>