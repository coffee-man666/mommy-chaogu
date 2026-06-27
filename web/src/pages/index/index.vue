<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getSnapshot } from '../../api'
import { QuotesWS } from '../../api/ws'
import { fmtPrice, fmtPct, fmtMoney, fmtAge, changeColor } from '../../api'
import type { Snapshot, Quote } from '../../api/types'

const router = useRouter()
const snapshot = ref<Snapshot | null>(null)
const loading = ref(true)
const ws = new QuotesWS()

const snapshotAgeSec = ref(0)

let ageTimer: number | null = null

const dataDescription = computed(() => {
  if (!snapshot.value) return '-'
  const ts = new Date(snapshot.value.timestamp)
  const dataTs = new Date(snapshot.value.quotes[0]?.timestamp || ts)
  const now = new Date()
  // 用数据时间（最早一支股票的时间戳）来描述
  const dataAgeHrs = (now.getTime() - dataTs.getTime()) / 1000 / 3600
  if (dataAgeHrs < 0.5) return '今日盘中'
  if (dataAgeHrs < 16) return '今日收盘'
  if (dataAgeHrs < 40) return '昨日收盘'
  return `${Math.floor(dataAgeHrs / 24)}天前`
})

async function refresh() {
  try {
    loading.value = true
    snapshot.value = await getSnapshot()
    snapshotAgeSec.value = 0
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function goDetail(quote: Quote) {
  router.push({ name: 'detail', params: { code: quote.code } })
}

function onUpdate(snap: Snapshot) {
  snapshot.value = snap
  snapshotAgeSec.value = 0
}

function flowArrowColor(netInflow: string | null): string {
  if (!netInflow) return '#999'
  return Number(netInflow) >= 0 ? '#c83e3e' : '#2d8e3d'
}

function flowSign(netInflow: string | null): string {
  if (!netInflow) return ''
  return Number(netInflow) >= 0 ? '+' : ''
}

onMounted(() => {
  refresh()
  ws.connect(onUpdate)
  // 每秒刷新一次"快照年龄"，前端体验更好
  ageTimer = window.setInterval(() => {
    snapshotAgeSec.value++
  }, 1000)
})

onUnmounted(() => {
  ws.disconnect()
  if (ageTimer) clearInterval(ageTimer)
})
</script>

<template>
  <div class="dashboard">
    <header class="header">
      <div class="header-row">
        <div class="header-title">妈妈炒股</div>
        <div class="header-time">
          <span class="data-badge">{{ dataDescription }}</span>
          <span class="dot-sep">·</span>
          <span class="age-text">{{ snapshotAgeSec }}秒前</span>
        </div>
      </div>
      <div class="header-stats" v-if="snapshot">
        <span class="stat-num">{{ snapshot.n_codes }}</span>
        <span class="stat-label">只</span>
        <span class="stat-up">↑{{ snapshot.n_up }}</span>
        <span class="stat-down">↓{{ snapshot.n_down }}</span>
        <span class="stat-flat">平{{ snapshot.n_flat }}</span>
      </div>
      <div class="header-flow" v-if="snapshot">
        主力合计
        <span class="flow-value" :style="{ color: Number(snapshot.total_main_net) >= 0 ? '#ff8a8a' : '#69db7c' }">
          {{ flowSign(snapshot.total_main_net) }}{{ fmtMoney(snapshot.total_main_net, 'yi') }}
        </span>
      </div>
    </header>

    <!-- 骨架屏 -->
    <div class="quote-list" v-if="loading && !snapshot">
      <div v-for="i in 5" :key="i" class="quote-row skeleton-row">
        <div class="quote-left">
          <div class="skeleton sk-name"></div>
          <div class="skeleton sk-code"></div>
        </div>
        <div class="quote-mid">
          <div class="skeleton sk-price"></div>
        </div>
        <div class="quote-right">
          <div class="skeleton sk-flow"></div>
        </div>
      </div>
    </div>

    <div class="quote-list" v-else-if="snapshot && snapshot.quotes.length">
      <div
        v-for="q in snapshot.quotes"
        :key="q.code"
        class="quote-row"
        @click="goDetail(q)"
      >
        <div class="quote-left">
          <div class="quote-name" :style="{ color: changeColor(q.change_pct) }">{{ q.name }}</div>
          <div class="quote-code">{{ q.code }} · {{ q.market }}</div>
        </div>
        <div class="quote-mid">
          <div class="quote-price" :style="{ color: changeColor(q.change_pct) }">
            {{ fmtPrice(q.price) }}
          </div>
          <div class="quote-pct" :style="{ color: changeColor(q.change_pct) }">
            {{ fmtPct(q.change_pct) }}
          </div>
        </div>
        <div class="quote-right">
          <div class="quote-flow" :style="{ color: flowArrowColor(q.main_net_inflow) }" v-if="q.main_net_inflow">
            <span class="flow-arrow">{{ Number(q.main_net_inflow) >= 0 ? '▲' : '▼' }}</span>
            {{ flowSign(q.main_net_inflow) }}{{ fmtMoney(q.main_net_inflow, 'yi') }}
          </div>
          <div class="quote-flow-label">主力</div>
        </div>
      </div>
    </div>

    <div class="empty" v-else>
      <div class="empty-icon">📭</div>
      <div class="empty-text">暂无自选股</div>
      <div class="empty-hint">去「设置」→「+ 添加」加股票</div>
      <button class="empty-btn" @click="router.push('/settings')">去添加</button>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  min-height: 100vh;
  background: #f5f5f5;
}

.header {
  background: linear-gradient(135deg, #c83e3e, #a52828);
  color: white;
  padding: 18px 16px 16px;
}

.header-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
}

.header-title {
  font-size: 26px;
  font-weight: bold;
}

.header-time {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  opacity: 0.95;
}

.data-badge {
  background: rgba(255, 255, 255, 0.18);
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.dot-sep {
  opacity: 0.5;
}

.age-text {
  font-family: 'Courier New', monospace;
}

.header-stats {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 16px;
  margin-bottom: 6px;
}

.stat-num { font-size: 32px; font-weight: bold; margin-right: 2px; line-height: 1; }
.stat-label { font-size: 14px; opacity: 0.85; margin-right: 4px; }
.stat-up { color: #ff8a8a; margin-right: 6px; font-weight: 600; }
.stat-down { color: #69db7c; margin-right: 6px; font-weight: 600; }
.stat-flat { opacity: 0.85; font-weight: 600; }

.header-flow {
  font-size: 13px;
  opacity: 0.9;
}

.flow-value {
  font-weight: 700;
  font-size: 15px;
  font-family: 'Courier New', monospace;
  margin-left: 4px;
}

.quote-list {
  background: white;
}

.quote-row {
  display: flex;
  align-items: center;
  padding: 18px 16px;
  border-bottom: 1px solid #eee;
  cursor: pointer;
  min-height: 72px;
}

.quote-row:active { background: #f8f8f8; }

.quote-left { flex: 1; min-width: 0; }

.quote-name {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.quote-code {
  font-size: 12px;
  color: #999;
}

.quote-mid {
  text-align: right;
  margin-right: 14px;
  min-width: 90px;
}

.quote-price {
  font-size: 22px;
  font-weight: bold;
  font-family: 'Courier New', monospace;
  line-height: 1.1;
}

.quote-pct {
  font-size: 14px;
  margin-top: 3px;
  font-family: 'Courier New', monospace;
  font-weight: 600;
}

.quote-right {
  text-align: right;
  min-width: 100px;
}

.quote-flow {
  font-size: 15px;
  font-family: 'Courier New', monospace;
  font-weight: 600;
}

.flow-arrow {
  font-size: 10px;
  margin-right: 2px;
}

.quote-flow-label {
  font-size: 11px;
  color: #999;
  margin-top: 2px;
}

/* 骨架屏 */
.skeleton {
  background: linear-gradient(90deg, #eee, #f5f5f5, #eee);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 4px;
  height: 14px;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.skeleton-row .sk-name { width: 80px; height: 18px; margin-bottom: 6px; }
.skeleton-row .sk-code { width: 90px; height: 12px; }
.skeleton-row .sk-price { width: 70px; height: 22px; }
.skeleton-row .sk-flow { width: 80px; height: 14px; }

/* 空态 */
.empty {
  padding: 80px 16px;
  text-align: center;
  background: white;
}

.empty-icon {
  font-size: 56px;
  margin-bottom: 16px;
  opacity: 0.6;
}

.empty-text {
  font-size: 18px;
  color: #666;
  margin-bottom: 6px;
  font-weight: 600;
}

.empty-hint {
  font-size: 13px;
  color: #999;
  margin-bottom: 24px;
}

.empty-btn {
  background: #c83e3e;
  color: white;
  border: none;
  padding: 12px 32px;
  border-radius: 24px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.empty-btn:active {
  background: #a52828;
}
</style>
