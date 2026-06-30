<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { recentSignals, signalHistory } from '../../api/signals'
import type { Signal } from '../../api/types'

const router = useRouter()
const recentSignalsList = ref<Signal[]>([])
const history = ref<Signal[]>([])
const tab = ref<'recent' | 'history'>('recent')

async function load() {
  try {
    recentSignalsList.value = await recentSignals()
    history.value = await signalHistory(50)
  } catch (e) {
    console.error(e)
  }
}

function severityClass(s: Signal['severity']): string {
  return `signal-${s}`
}

function severityLabel(s: Signal['severity']): string {
  return { info: 'INFO', warning: 'WARN', critical: 'CRIT' }[s]
}

function severityIcon(s: Signal['severity']): string {
  return { info: 'ℹ️', warning: '⚠️', critical: '🚨' }[s]
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  if (sameDay) {
    return d.toTimeString().slice(0, 8)
  }
  return `${d.getMonth() + 1}/${d.getDate()} ${d.toTimeString().slice(0, 5)}`
}

function goDetail(s: Signal) {
  if (s.code && /^\d{6}$/.test(s.code)) {
    router.push({ name: 'detail', params: { code: s.code } })
  }
}

function isStockCode(code: string): boolean {
  return /^\d{6}$/.test(code)
}

let timer: number | null = null

onMounted(() => {
  load()
  timer = window.setInterval(load, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="signals-page">
    <header class="header">
      <div class="title">信号中心</div>
      <div class="subtitle" v-if="tab === 'recent'">{{ recentSignalsList.length }} 条触发 · 实时</div>
      <div class="subtitle" v-else>最近 {{ history.length }} 条历史</div>
    </header>

    <div class="tabs">
      <div
        :class="['tab', { active: tab === 'recent' }]"
        @click="tab = 'recent'"
      >本次触发 ({{ recentSignalsList.length }})</div>
      <div
        :class="['tab', { active: tab === 'history' }]"
        @click="tab = 'history'"
      >历史信号</div>
    </div>

    <div class="signal-list" v-if="tab === 'recent' && recentSignalsList.length">
      <div
        v-for="s in recentSignalsList"
        :key="`${s.timestamp}-${s.code}-${s.rule_id}`"
        :class="['signal-card', severityClass(s.severity)]"
        @click="goDetail(s)"
      >
        <div class="signal-head">
          <span :class="['severity-tag', severityClass(s.severity)]">
            {{ severityIcon(s.severity) }} {{ severityLabel(s.severity) }}
          </span>
          <span class="signal-code">{{ s.code }} {{ s.name }}</span>
          <span class="signal-time">{{ fmtTime(s.timestamp) }}</span>
        </div>
        <div class="signal-title">{{ s.title }}</div>
        <div class="signal-detail">{{ s.detail }}</div>
        <div class="signal-action" v-if="isStockCode(s.code)">点击查看 K 线 ›</div>
      </div>
    </div>

    <div class="signal-list" v-else-if="tab === 'history' && history.length">
      <div
        v-for="s in history"
        :key="`${s.timestamp}-${s.code}-${s.rule_id}`"
        :class="['signal-card', severityClass(s.severity)]"
        @click="goDetail(s)"
      >
        <div class="signal-head">
          <span :class="['severity-tag', severityClass(s.severity)]">
            {{ severityIcon(s.severity) }} {{ severityLabel(s.severity) }}
          </span>
          <span class="signal-code">{{ s.code }} {{ s.name }}</span>
          <span class="signal-time">{{ fmtTime(s.timestamp) }}</span>
        </div>
        <div class="signal-title">{{ s.title }}</div>
        <div class="signal-detail">{{ s.detail }}</div>
      </div>
    </div>

    <div class="empty" v-else>
      <div class="empty-icon">{{ tab === 'recent' ? '🌤️' : '📭' }}</div>
      <div class="empty-text">{{ tab === 'recent' ? '本次轮询未触发信号' : '暂无历史信号' }}</div>
      <div class="empty-hint" v-if="tab === 'recent'">行情平稳，妈妈放心 ✨</div>
    </div>
  </div>
</template>

<style scoped>
.signals-page {
  min-height: 100vh;
  background: var(--color-bg);
}

.header {
  background: var(--color-primary);
  color: white;
  padding: 18px 16px 14px;
}

.title {
  font-size: 24px;
  font-weight: bold;
  margin-bottom: 4px;
}

.subtitle {
  font-size: 12px;
  opacity: 0.85;
}

.tabs {
  display: flex;
  background: white;
  border-bottom: 1px solid #eee;
}

.tab {
  flex: 1;
  text-align: center;
  padding: 14px 0;
  font-size: 14px;
  color: #666;
  border-bottom: 3px solid transparent;
  cursor: pointer;
  user-select: none;
  font-weight: 500;
}

.tab.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
  font-weight: 700;
}

.signal-list {
  padding: 12px;
}

.signal-card {
  background: white;
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 12px;
  border-left: 5px solid #ddd;
  cursor: pointer;
  transition: transform 0.1s;
}

.signal-card:active {
  transform: scale(0.98);
  background: var(--color-bg);
}

.signal-card.signal-critical {
  border-left-color: var(--color-primary);
  background: linear-gradient(to right, var(--color-bg), white);
}

.signal-card.signal-warning {
  border-left-color: #f59e0b;
  background: linear-gradient(to right, #fffaf0, white);
}

.signal-card.signal-info {
  border-left-color: #6b7280;
}

.signal-head {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  gap: 8px;
  flex-wrap: wrap;
}

.severity-tag {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 4px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.severity-tag.signal-critical { background: var(--color-primary); color: white; }
.severity-tag.signal-warning { background: #f59e0b; color: white; }
.severity-tag.signal-info { background: #6b7280; color: white; }

.signal-code {
  font-size: 15px;
  font-weight: 700;
  flex: 1;
  min-width: 0;
}

.signal-time {
  font-size: 12px;
  color: #999;
  font-family: 'Courier New', monospace;
}

.signal-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 6px;
  color: #222;
  line-height: 1.4;
}

.signal-detail {
  font-size: 13px;
  color: #666;
  line-height: 1.5;
}

.signal-action {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-primary);
  font-weight: 600;
}

.empty {
  padding: 80px 16px;
  text-align: center;
  background: white;
  margin-top: 12px;
}

.empty-icon {
  font-size: 56px;
  margin-bottom: 16px;
}

.empty-text {
  font-size: 17px;
  color: #666;
  margin-bottom: 6px;
  font-weight: 600;
}

.empty-hint {
  font-size: 13px;
  color: #999;
}
</style>
