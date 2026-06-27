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

const lastUpdate = computed(() => {
  if (!snapshot.value) return '-'
  return fmtAge(Math.max(0, Math.floor((Date.now() - new Date(snapshot.value.timestamp).getTime()) / 1000)))
})

async function refresh() {
  try {
    loading.value = true
    snapshot.value = await getSnapshot()
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
}

onMounted(() => {
  refresh()
  ws.connect(onUpdate)
})

onUnmounted(() => {
  ws.disconnect()
})
</script>

<template>
  <div class="dashboard">
    <header class="header">
      <div class="header-title">妈妈炒股</div>
      <div class="header-stats" v-if="snapshot">
        <span class="stat-num">{{ snapshot.n_codes }}</span>
        <span class="stat-label">只</span>
        <span class="stat-up">↑{{ snapshot.n_up }}</span>
        <span class="stat-down">↓{{ snapshot.n_down }}</span>
        <span class="stat-flat">平{{ snapshot.n_flat }}</span>
        <span class="stat-flow">主力 {{ fmtMoney(snapshot.total_main_net, 'yi') }}</span>
      </div>
      <div class="header-time">{{ lastUpdate }} · 实时</div>
    </header>

    <div class="quote-list" v-if="snapshot && snapshot.quotes.length">
      <div
        v-for="q in snapshot.quotes"
        :key="q.code"
        class="quote-row"
        @click="goDetail(q)"
      >
        <div class="quote-left">
          <div class="quote-name">{{ q.name }}</div>
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
          <div class="quote-flow" v-if="q.main_net_inflow">
            {{ Number(q.main_net_inflow) >= 0 ? '+' : '' }}{{ fmtMoney(q.main_net_inflow, 'yi') }}
          </div>
          <div class="quote-flow-label">主力</div>
        </div>
      </div>
    </div>

    <div class="empty" v-else-if="!loading">
      <div>暂无自选股</div>
      <div class="empty-hint">去「设置」添加股票</div>
    </div>

    <div class="loading" v-if="loading">
      <div>加载中...</div>
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
  padding: 20px 16px 16px;
}

.header-title {
  font-size: 24px;
  font-weight: bold;
  margin-bottom: 10px;
}

.header-stats {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 14px;
  flex-wrap: wrap;
}

.stat-num { font-size: 28px; font-weight: bold; margin-right: 2px; }
.stat-label { font-size: 14px; opacity: 0.8; margin-right: 10px; }
.stat-up { color: #ff8a8a; margin-right: 8px; }
.stat-down { color: #69db7c; margin-right: 8px; }
.stat-flat { opacity: 0.8; margin-right: 8px; }
.stat-flow { margin-left: auto; opacity: 0.9; }

.header-time {
  font-size: 12px;
  opacity: 0.7;
  margin-top: 4px;
}

.quote-list {
  background: white;
}

.quote-row {
  display: flex;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #eee;
  cursor: pointer;
}

.quote-row:active { background: #f8f8f8; }

.quote-left { flex: 1; }

.quote-name {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 2px;
}

.quote-code {
  font-size: 12px;
  color: #999;
}

.quote-mid {
  text-align: right;
  margin-right: 16px;
  min-width: 80px;
}

.quote-price {
  font-size: 20px;
  font-weight: bold;
  font-family: 'Courier New', monospace;
}

.quote-pct {
  font-size: 13px;
  margin-top: 2px;
  font-family: 'Courier New', monospace;
}

.quote-right {
  text-align: right;
  min-width: 90px;
}

.quote-flow {
  font-size: 14px;
  color: #c83e3e;
  font-family: 'Courier New', monospace;
}

.quote-flow-label {
  font-size: 11px;
  color: #999;
  margin-top: 1px;
}

.empty, .loading {
  padding: 60px 16px;
  text-align: center;
  color: #999;
}

.empty-hint {
  font-size: 12px;
  color: #ccc;
  margin-top: 4px;
}
</style>
