<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getPortfolio, addPosition, removePosition, listAdjustments, addAdjustment } from '../../api/portfolio'
import { fmtPrice, fmtPct, fmtMoney, changeColor } from '../../api'
import type { PortfolioSummary, PositionDetail, Adjustment } from '../../api/types'
import { useSpeechRecognition } from '../../composables/useSpeechRecognition'

const router = useRouter()
const portfolio = ref<PortfolioSummary | null>(null)
const loading = ref(true)
const showAdd = ref(false)
const adding = ref(false)
const removing = ref<number | null>(null)

// 调仓展开 + 表单
const expandedAdj = ref<number | null>(null)
const adjustmentsMap = ref<Record<number, Adjustment[]>>({})
const adjLoading = ref(false)
const adjSubmitting = ref<number | null>(null)
const adjAction = ref<'buy' | 'sell' | 'dividend'>('buy')
const adjPrice = ref('')
const adjShares = ref('')
const adjDate = ref('')
const adjNote = ref('')

// 表单
const newCode = ref('')
const newName = ref('')
const newPrice = ref('')
const newShares = ref('')
const newDate = ref('')
const newNote = ref('')

// 语音
const { state: voiceState, transcript, error: voiceError, isSupported: voiceSupported, start: voiceStart, stop: voiceStop, parse: voiceParse } = useSpeechRecognition()
const showVoice = ref(false)
const voiceResult = ref<ReturnType<typeof voiceParse> | null>(null)

function startVoice() {
  showVoice.value = true
  voiceResult.value = null
  voiceStart()
}

function applyVoice() {
  const result = voiceParse(transcript.value)
  voiceResult.value = result
  if (result.code) newCode.value = result.code
  if (result.name) newName.value = result.name
  if (result.price) newPrice.value = result.price
  if (result.shares) newShares.value = result.shares
  showVoice.value = false
  showAdd.value = true
}

watch(voiceState, (s) => {
  if (s === 'done' || s === 'error') {
    // 自动解析结果
    if (s === 'done' && transcript.value) {
      voiceResult.value = voiceParse(transcript.value)
    }
  }
})

let refreshTimer: number | null = null

async function load() {
  try {
    portfolio.value = await getPortfolio()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function doAdd() {
  if (!newCode.value.trim() || !newPrice.value.trim() || !newShares.value.trim()) {
    alert('请填写代码、买入价和股数')
    return
  }
  adding.value = true
  try {
    await addPosition({
      code: newCode.value.trim(),
      name: newName.value.trim() || undefined,
      buy_price: newPrice.value.trim(),
      shares: parseInt(newShares.value.trim()),
      buy_date: newDate.value || undefined,
      note: newNote.value || undefined,
    })
    newCode.value = ''
    newName.value = ''
    newPrice.value = ''
    newShares.value = ''
    newDate.value = ''
    newNote.value = ''
    showAdd.value = false
    await load()
  } catch (e: any) {
    alert('添加失败: ' + (e.message || e))
  } finally {
    adding.value = false
  }
}

async function doRemove(pos: PositionDetail) {
  if (!confirm(`确认清仓「${pos.name || pos.code}」(${pos.shares}股)?`)) return
  removing.value = pos.id
  try {
    await removePosition(pos.id)
    await load()
  } catch (e: any) {
    alert('删除失败: ' + (e.message || e))
  } finally {
    removing.value = null
  }
}

function goDetail(code: string) {
  router.push({ name: 'detail', params: { code } })
}

// ---- 调仓 ----

function actionLabel(action: string): string {
  if (action === 'buy') return '加仓'
  if (action === 'sell') return '减仓'
  return '分红'
}

function actionColor(action: string): string {
  if (action === 'buy') return '#c83e3e'
  if (action === 'sell') return '#2d8e3d'
  return '#b8860b'
}

async function toggleAdj(p: PositionDetail) {
  if (expandedAdj.value === p.id) {
    expandedAdj.value = null
    return
  }
  expandedAdj.value = p.id
  // 重置表单
  adjAction.value = 'buy'
  adjPrice.value = ''
  adjShares.value = ''
  adjDate.value = ''
  adjNote.value = ''
  // 拉历史记录
  if (!adjustmentsMap.value[p.id]) {
    adjLoading.value = true
    try {
      adjustmentsMap.value[p.id] = await listAdjustments(p.id)
    } catch (e) {
      console.error(e)
      adjustmentsMap.value[p.id] = []
    } finally {
      adjLoading.value = false
    }
  }
}

async function submitAdj(p: PositionDetail) {
  if (!adjPrice.value.trim() || !adjShares.value.trim()) {
    alert('请填写价格和股数')
    return
  }
  adjSubmitting.value = p.id
  try {
    // 后端 AddAdjustmentIn 无 date 字段，日期拼入 note 保留
    const noteParts: string[] = []
    if (adjDate.value) noteParts.push(`[${adjDate.value}]`)
    if (adjNote.value.trim()) noteParts.push(adjNote.value.trim())
    await addAdjustment(p.id, {
      action: adjAction.value,
      price: adjPrice.value.trim(),
      shares: parseInt(adjShares.value.trim()),
      note: noteParts.join(' '),
    })
    // 刷新记录 + 持仓
    adjustmentsMap.value[p.id] = await listAdjustments(p.id)
    adjPrice.value = ''
    adjShares.value = ''
    adjDate.value = ''
    adjNote.value = ''
    adjAction.value = 'buy'
    await load()
  } catch (e: any) {
    alert('调仓失败: ' + (e.message || e))
  } finally {
    adjSubmitting.value = null
  }
}

function pnlColor(pnl: string | null): string {
  if (!pnl) return '#999'
  return Number(pnl) >= 0 ? 'var(--color-primary)' : 'var(--color-down)'
}

function pnlSign(pnl: string | null): string {
  if (!pnl) return ''
  return Number(pnl) >= 0 ? '+' : ''
}

function fmtWan(s: string | null): string {
  if (!s) return '-'
  const n = Number(s)
  if (isNaN(n)) return s
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(2)
}

onMounted(() => {
  load()
  refreshTimer = window.setInterval(load, 10000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="portfolio-page">
    <!-- 总览卡片 -->
    <header class="header" v-if="portfolio && portfolio.n_positions > 0">
      <div class="header-row">
        <div class="header-title">💰 我的持仓</div>
        <div class="header-actions">
          <span class="voice-btn" @click="startVoice" v-if="voiceSupported">
            🎙️
          </span>
          <span class="add-btn" @click="showAdd = !showAdd">
            {{ showAdd ? '✕' : '+ 录入' }}
          </span>
        </div>
      </div>
      <div class="pnl-card">
        <div class="pnl-label">总市值</div>
        <div class="pnl-value">
          <span class="big-num">{{ fmtWan(portfolio.total_market_value) }}</span>
        </div>
        <div class="pnl-detail">
          <div class="pnl-item">
            <span class="lbl">总成本</span>
            <span class="val">{{ fmtWan(portfolio.total_cost) }}</span>
          </div>
          <div class="pnl-item">
            <span class="lbl">浮盈亏</span>
            <span class="val" :style="{ color: pnlColor(portfolio.total_unrealized_pnl) }">
              {{ pnlSign(portfolio.total_unrealized_pnl) }}{{ fmtWan(portfolio.total_unrealized_pnl) }}
            </span>
          </div>
          <div class="pnl-item">
            <span class="lbl">盈亏率</span>
            <span class="val" :style="{ color: pnlColor(portfolio.total_unrealized_pnl_pct) }">
              {{ fmtPct(portfolio.total_unrealized_pnl_pct || '0') }}
            </span>
          </div>
        </div>
      </div>
    </header>

    <!-- 空状态 header -->
    <header class="header header-empty" v-else-if="!loading">
      <div class="header-row">
        <div class="header-title">💰 我的持仓</div>
        <div class="header-actions">
          <span class="voice-btn" @click="startVoice" v-if="voiceSupported">
            🎙️
          </span>
          <span class="add-btn" @click="showAdd = !showAdd">
            {{ showAdd ? '✕' : '+ 录入' }}
          </span>
        </div>
      </div>
      <div class="empty-inline">还没有持仓记录，点击「+ 录入」添加</div>
    </header>

    <!-- 录入表单 -->
    <div class="add-form-card" v-if="showAdd">
      <div class="form-title">录入买入</div>
      <div class="form-row">
        <input v-model="newCode" placeholder="股票代码（如 600519）" class="input" inputmode="numeric" maxlength="6" />
        <input v-model="newName" placeholder="名称（可选，如 贵州茅台）" class="input" />
      </div>
      <div class="form-row">
        <input v-model="newPrice" placeholder="买入价（如 1680.50）" class="input" inputmode="decimal" />
        <input v-model="newShares" placeholder="股数（如 100）" class="input" inputmode="numeric" />
      </div>
      <div class="form-row">
        <input v-model="newDate" type="date" class="input" />
        <input v-model="newNote" placeholder="备注（可选）" class="input" />
      </div>
      <button class="submit-btn" @click="doAdd" :disabled="adding">
        {{ adding ? '保存中...' : '保存' }}
      </button>
    </div>

    <!-- 持仓列表 -->
    <div class="position-list" v-if="portfolio && portfolio.positions.length">
      <div
        v-for="p in portfolio.positions"
        :key="p.id"
        class="position-row"
      >
        <div class="pos-top">
          <div class="pos-main" @click="goDetail(p.code)">
            <div class="pos-header">
              <span class="pos-name">{{ p.name || p.code }}</span>
              <span class="pos-code">{{ p.code }}</span>
            </div>
            <div class="pos-data">
              <div class="pos-cell">
                <span class="cell-label">成本</span>
                <span class="cell-val">{{ fmtPrice(p.avg_cost) }}</span>
              </div>
              <div class="pos-cell">
                <span class="cell-label">现价</span>
                <span class="cell-val" :style="{ color: changeColor(((Number(p.current_price) - Number(p.avg_cost)) / Number(p.avg_cost) * 100).toFixed(2)) }">
                  {{ p.current_price ? fmtPrice(p.current_price) : '-' }}
                </span>
              </div>
              <div class="pos-cell">
                <span class="cell-label">股数</span>
                <span class="cell-val">{{ p.shares }}</span>
              </div>
              <div class="pos-cell">
                <span class="cell-label">市值</span>
                <span class="cell-val">{{ fmtWan(p.market_value) }}</span>
              </div>
            </div>
            <div class="pos-pnl-row" v-if="p.unrealized_pnl">
              <span class="pnl-tag" :style="{ background: pnlColor(p.unrealized_pnl) }">
                {{ pnlSign(p.unrealized_pnl) }}{{ fmtWan(p.unrealized_pnl) }}
                ({{ fmtPct(p.unrealized_pnl_pct || '0') }})
              </span>
            </div>
          </div>
          <div class="pos-side-btns">
            <button
              class="adj-toggle-btn"
              @click="toggleAdj(p)"
            >
              {{ expandedAdj === p.id ? '收起' : '＋调仓' }}
            </button>
            <button
              class="clear-btn"
              @click="doRemove(p)"
              :disabled="removing === p.id"
            >
              {{ removing === p.id ? '...' : '清仓' }}
            </button>
          </div>
        </div>

        <!-- 调仓区域 -->
        <div class="adj-area" v-if="expandedAdj === p.id">
          <!-- 调仓表单 -->
          <div class="adj-form">
            <div class="adj-form-title">记录调仓</div>
            <div class="adj-form-row">
              <select v-model="adjAction" class="adj-select">
                <option value="buy">加仓</option>
                <option value="sell">减仓</option>
                <option value="dividend">分红</option>
              </select>
              <input v-model="adjPrice" placeholder="价格" class="adj-input" inputmode="decimal" />
              <input v-model="adjShares" placeholder="股数" class="adj-input" inputmode="numeric" />
            </div>
            <div class="adj-form-row">
              <input v-model="adjDate" type="date" class="adj-input" />
              <input v-model="adjNote" placeholder="备注（可选）" class="adj-input" />
            </div>
            <button
              class="adj-submit-btn"
              @click="submitAdj(p)"
              :disabled="adjSubmitting === p.id"
            >
              {{ adjSubmitting === p.id ? '提交中...' : '提交' }}
            </button>
          </div>

          <!-- 历史调仓记录 -->
          <div class="adj-history" v-if="adjustmentsMap[p.id] && adjustmentsMap[p.id].length">
            <div class="adj-history-title">历史记录</div>
            <div class="adj-timeline">
              <div
                v-for="adj in adjustmentsMap[p.id]"
                :key="adj.id"
                class="timeline-item"
              >
                <div class="timeline-dot" :style="{ background: actionColor(adj.action) }"></div>
                <div class="timeline-body">
                  <div class="timeline-head">
                    <span class="timeline-action" :style="{ color: actionColor(adj.action) }">{{ actionLabel(adj.action) }}</span>
                    <span class="timeline-price">{{ fmtPrice(adj.price) }} × {{ adj.shares }}股</span>
                  </div>
                  <div class="timeline-meta">
                    <span class="timeline-date">{{ adj.timestamp.slice(0, 16).replace('T', ' ') }}</span>
                    <span class="timeline-note" v-if="adj.note">{{ adj.note }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="adj-history-empty" v-else-if="!adjLoading">
            暂无调仓记录
          </div>
          <div class="adj-history-empty" v-else>
            加载中...
          </div>
        </div>
      </div>
    </div>

    <!-- 加载骨架 -->
    <div class="loading-box" v-if="loading">
      <div class="loading-text">加载中...</div>
    </div>

    <!-- 语音录入弹窗 -->
    <div class="voice-overlay" v-if="showVoice" @click.self="showVoice = false">
      <div class="voice-modal">
        <div class="voice-header">
          <span class="voice-title">🎙️ 语音录入</span>
          <span class="voice-close" @click="showVoice = false">✕</span>
        </div>
        <div class="voice-body">
          <div class="voice-mic" :class="{ listening: voiceState === 'listening' }" @click="voiceState === 'listening' ? voiceStop() : startVoice()">
            <span class="mic-icon">{{ voiceState === 'listening' ? '🔴' : '🎙️' }}</span>
          </div>
          <div class="voice-hint" v-if="voiceState === 'listening'">正在听...</div>
          <div class="voice-hint" v-else-if="voiceState === 'idle'">点击麦克风开始说话</div>
          <div class="voice-hint" v-else-if="voiceState === 'done'">识别完成</div>
          <div class="voice-hint error" v-else-if="voiceState === 'error'">{{ voiceError }}</div>

          <div class="voice-transcript" v-if="transcript">
            "{{ transcript }}"
          </div>

          <!-- 解析结果预览 -->
          <div class="voice-parsed" v-if="voiceResult">
            <div class="parsed-row" v-if="voiceResult.code"><span>代码</span><span>{{ voiceResult.code }}</span></div>
            <div class="parsed-row" v-if="voiceResult.name"><span>名称</span><span>{{ voiceResult.name }}</span></div>
            <div class="parsed-row" v-if="voiceResult.price"><span>买入价</span><span>{{ voiceResult.price }}</span></div>
            <div class="parsed-row" v-if="voiceResult.shares"><span>股数</span><span>{{ voiceResult.shares }}</span></div>
          </div>

          <div class="voice-tips">
            试试说：<br>
            "贵州茅台 600519 买入价1680 100股"<br>
            "五粮液 000858 成本155 200股"
          </div>

          <button class="voice-apply-btn" @click="applyVoice" v-if="transcript">
            填入表单 ✅
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.portfolio-page {
  min-height: 100vh;
  background: var(--color-bg);
  padding-bottom: 24px;
}

.header {
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-dark));
  color: white;
  padding: 18px 16px 16px;
}

.header-empty {
  padding-bottom: 24px;
}

.header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.header-title {
  font-size: 24px;
  font-weight: bold;
}

.add-btn {
  background: rgba(255, 255, 255, 0.25);
  color: white;
  padding: 6px 16px;
  border-radius: 16px;
  font-size: 14px;
  cursor: pointer;
  font-weight: 600;
  user-select: none;
}

.add-btn:active { background: rgba(255, 255, 255, 0.4); }

.empty-inline {
  font-size: 14px;
  opacity: 0.9;
  text-align: center;
  padding: 8px 0;
}

/* 总览卡片 */
.pnl-card {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 16px;
}

.pnl-label {
  font-size: 13px;
  opacity: 0.85;
  margin-bottom: 4px;
}

.pnl-value {
  margin-bottom: 12px;
}

.big-num {
  font-size: 36px;
  font-weight: bold;
  font-family: 'Courier New', monospace;
  line-height: 1.1;
}

.pnl-detail {
  display: flex;
  gap: 16px;
}

.pnl-item {
  flex: 1;
}

.pnl-item .lbl {
  display: block;
  font-size: 11px;
  opacity: 0.8;
  margin-bottom: 2px;
}

.pnl-item .val {
  font-size: 16px;
  font-weight: 700;
  font-family: 'Courier New', monospace;
}

/* 录入表单 */
.add-form-card {
  background: white;
  margin: 12px;
  padding: 16px;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.form-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 12px;
}

.form-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.input {
  flex: 1;
  background: #f8f8f8;
  padding: 10px;
  border-radius: 6px;
  font-size: 14px;
  border: 1px solid #ddd;
  font-family: inherit;
  box-sizing: border-box;
}

.input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.submit-btn {
  background: var(--color-primary);
  color: white;
  padding: 12px;
  border-radius: 8px;
  font-size: 15px;
  width: 100%;
  border: none;
  cursor: pointer;
  font-weight: 600;
  margin-top: 4px;
}

.submit-btn:disabled { opacity: 0.6; }
.submit-btn:active:not(:disabled) { background: var(--color-primary-dark); }

/* 持仓列表 */
.position-list {
  background: white;
  margin: 0 12px;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.position-row {
  border-bottom: 1px solid var(--color-bg);
}

.position-row:last-child { border-bottom: none; }

.pos-top {
  display: flex;
  align-items: stretch;
}

.pos-side-btns {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  border-left: 1px solid #f0f0f0;
}

.adj-toggle-btn {
  flex: 1;
  color: var(--color-primary);
  font-size: 12px;
  background: white;
  border: none;
  cursor: pointer;
  font-weight: 600;
  padding: 0 8px;
  white-space: nowrap;
  min-width: 56px;
}

.adj-toggle-btn:active {
  background: var(--color-bg);
}

.pos-main {
  flex: 1;
  padding: 14px 16px;
  cursor: pointer;
}

.pos-main:active { background: var(--color-bg); }

.pos-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.pos-name {
  font-size: 18px;
  font-weight: 600;
}

.pos-code {
  font-size: 12px;
  color: #999;
}

.pos-data {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}

.pos-cell {
  flex: 1;
  text-align: center;
}

.cell-label {
  display: block;
  font-size: 11px;
  color: #999;
  margin-bottom: 2px;
}

.cell-val {
  font-size: 14px;
  font-weight: 600;
  font-family: 'Courier New', monospace;
}

.pos-pnl-row {
  display: flex;
  align-items: center;
}

.pnl-tag {
  display: inline-block;
  color: white;
  font-size: 13px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 12px;
  font-family: 'Courier New', monospace;
}

.clear-btn {
  flex: 1;
  color: #999;
  font-size: 13px;
  background: white;
  border: none;
  border-top: 1px solid #f0f0f0;
  cursor: pointer;
  font-weight: 500;
  padding: 0 8px;
  white-space: nowrap;
  min-width: 56px;
}

.clear-btn:active:not(:disabled) {
  background: var(--color-bg);
  color: var(--color-primary);
}

.clear-btn:disabled { opacity: 0.5; }

/* 调仓区域 */
.adj-area {
  background: #fafafa;
  padding: 14px 16px;
  border-top: 1px solid #f0f0f0;
}

.adj-form {
  background: white;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
  border: 1px solid #eee;
}

.adj-form-title {
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 8px;
  color: #555;
}

.adj-form-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.adj-select {
  flex: 0 0 auto;
  background: #f8f8f8;
  padding: 8px;
  border-radius: 6px;
  font-size: 14px;
  border: 1px solid #ddd;
  font-family: inherit;
}

.adj-input {
  flex: 1;
  background: #f8f8f8;
  padding: 8px;
  border-radius: 6px;
  font-size: 14px;
  border: 1px solid #ddd;
  font-family: inherit;
  box-sizing: border-box;
  min-width: 0;
}

.adj-input:focus,
.adj-select:focus {
  outline: none;
  border-color: var(--color-primary);
}

.adj-submit-btn {
  background: var(--color-primary);
  color: white;
  padding: 9px;
  border-radius: 6px;
  font-size: 14px;
  width: 100%;
  border: none;
  cursor: pointer;
  font-weight: 600;
  margin-top: 2px;
}

.adj-submit-btn:disabled { opacity: 0.6; }
.adj-submit-btn:active:not(:disabled) { background: var(--color-primary-dark); }

/* 调仓历史时间线 */
.adj-history-title {
  font-size: 12px;
  font-weight: 700;
  color: #999;
  margin-bottom: 8px;
}

.adj-timeline {
  position: relative;
}

.timeline-item {
  display: flex;
  gap: 10px;
  padding-bottom: 12px;
  position: relative;
}

.timeline-item:last-child { padding-bottom: 0; }

.timeline-item:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 12px;
  bottom: 0;
  width: 2px;
  background: #e0e0e0;
}

.timeline-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 4px;
  z-index: 1;
}

.timeline-body {
  flex: 1;
  min-width: 0;
}

.timeline-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 2px;
}

.timeline-action {
  font-size: 14px;
  font-weight: 700;
}

.timeline-price {
  font-size: 13px;
  font-weight: 600;
  font-family: 'Courier New', monospace;
  color: #333;
}

.timeline-meta {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}

.timeline-date {
  color: #aaa;
  font-family: 'Courier New', monospace;
}

.timeline-note {
  color: #666;
}

.adj-history-empty {
  text-align: center;
  font-size: 13px;
  color: #bbb;
  padding: 12px 0;
}

.loading-box {
  padding: 60px 0;
  text-align: center;
}

.loading-text {
  color: #999;
  font-size: 14px;
}

/* 语音按钮 */
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.voice-btn {
  background: rgba(255, 255, 255, 0.25);
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 18px;
  cursor: pointer;
  user-select: none;
}

.voice-btn:active { background: rgba(255, 255, 255, 0.4); }

/* 语音弹窗 */
.voice-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
}

.voice-modal {
  background: white;
  width: 88%;
  max-width: 360px;
  border-radius: 16px;
  overflow: hidden;
}

.voice-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #eee;
}

.voice-title { font-size: 16px; font-weight: 700; }
.voice-close { font-size: 18px; color: #999; cursor: pointer; }

.voice-body {
  padding: 24px 16px 20px;
  text-align: center;
}

.voice-mic {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: #f0f0f0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.voice-mic.listening {
  background: #fff0f0;
  animation: pulse 1.2s infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(200, 62, 62, 0.4); }
  50% { transform: scale(1.05); box-shadow: 0 0 0 12px rgba(200, 62, 62, 0); }
}

.mic-icon { font-size: 32px; }

.voice-hint {
  font-size: 14px;
  color: #666;
  margin-bottom: 12px;
}

.voice-hint.error { color: var(--color-primary); }

.voice-transcript {
  background: #f8f8f8;
  padding: 12px;
  border-radius: 8px;
  font-size: 16px;
  color: #333;
  margin-bottom: 12px;
  line-height: 1.5;
}

.voice-parsed {
  background: #f0fff0;
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 12px;
}

.parsed-row {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  font-size: 14px;
}

.parsed-row span:first-child { color: #999; }
.parsed-row span:last-child { font-weight: 600; font-family: 'Courier New', monospace; }

.voice-tips {
  font-size: 12px;
  color: #aaa;
  line-height: 1.6;
  margin-bottom: 16px;
}

.voice-apply-btn {
  background: var(--color-primary);
  color: white;
  border: none;
  padding: 12px;
  border-radius: 8px;
  font-size: 15px;
  width: 100%;
  cursor: pointer;
  font-weight: 600;
}

.voice-apply-btn:active { background: var(--color-primary-dark); }
</style>
