<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { recentSignals, signalHistory } from '../../api/signals'
import type { Signal } from '../../api/types'

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

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  if (sameDay) {
    return d.toTimeString().slice(0, 8)
  }
  return `${d.getMonth() + 1}/${d.getDate()} ${d.toTimeString().slice(0, 5)}`
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
      >
        <div class="signal-head">
          <span :class="['severity-tag', severityClass(s.severity)]">{{ severityLabel(s.severity) }}</span>
          <span class="signal-code">{{ s.code }} {{ s.name }}</span>
          <span class="signal-time">{{ fmtTime(s.timestamp) }}</span>
        </div>
        <div class="signal-title">{{ s.title }}</div>
        <div class="signal-detail">{{ s.detail }}</div>
      </div>
    </div>

    <div class="signal-list" v-else-if="tab === 'history' && history.length">
      <div
        v-for="s in history"
        :key="`${s.timestamp}-${s.code}-${s.rule_id}`"
        :class="['signal-card', severityClass(s.severity)]"
      >
        <div class="signal-head">
          <span :class="['severity-tag', severityClass(s.severity)]">{{ severityLabel(s.severity) }}</span>
          <span class="signal-code">{{ s.code }} {{ s.name }}</span>
          <span class="signal-time">{{ fmtTime(s.timestamp) }}</span>
        </div>
        <div class="signal-title">{{ s.title }}</div>
        <div class="signal-detail">{{ s.detail }}</div>
      </div>
    </div>

    <div class="empty" v-else>
      <div>{{ tab === 'recent' ? '本次轮询未触发信号' : '暂无历史信号' }}</div>
    </div>
  </div>
</template>

<style scoped>
.signals-page {
  min-height: 100vh;
  background: #f5f5f5;
}

.header {
  background: #c83e3e;
  color: white;
  padding: 20px 16px 16px;
}

.title {
  font-size: 24px;
  font-weight: bold;
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
  font-size: 15px;
  color: #666;
  border-bottom: 3px solid transparent;
  cursor: pointer;
  user-select: none;
}

.tab.active {
  color: #c83e3e;
  border-bottom-color: #c83e3e;
  font-weight: 600;
}

.signal-list {
  padding: 10px;
}

.signal-card {
  background: white;
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 10px;
  border-left: 4px solid #ddd;
}

.signal-card.signal-critical {
  border-left-color: #c83e3e;
  background: linear-gradient(to right, #fff5f5, white);
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
  margin-bottom: 6px;
  gap: 8px;
}

.severity-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: bold;
}

.severity-tag.signal-critical { background: #c83e3e; color: white; }
.severity-tag.signal-warning { background: #f59e0b; color: white; }
.severity-tag.signal-info { background: #6b7280; color: white; }

.signal-code {
  font-size: 14px;
  font-weight: 600;
  flex: 1;
}

.signal-time {
  font-size: 12px;
  color: #999;
}

.signal-title {
  font-size: 15px;
  font-weight: 500;
  margin-bottom: 6px;
  color: #333;
}

.signal-detail {
  font-size: 13px;
  color: #666;
  line-height: 1.5;
}

.empty {
  padding: 60px 16px;
  text-align: center;
  color: #999;
}
</style>
