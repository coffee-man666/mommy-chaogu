<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { usePortfolioStore } from '@/stores/portfolio'
import { fmtPrice, fmtPct, fmtWan } from '@/utils/format'
import { cn } from '@/lib/utils'
import type { PositionDetail, Adjustment } from '@/api/types'
import { useSpeechRecognition } from '@/composables/useSpeechRecognition'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const router = useRouter()
const store = usePortfolioStore()

// ---------- 派生 ----------
const summary = computed(() => store.summary)
const loading = computed(() => store.loading)
const positions = computed(() => store.positions)

function pnlClass(v: string | number | null | undefined): string {
  if (v == null) return 'text-muted-foreground'
  const n = Number(v)
  if (isNaN(n) || n === 0) return 'text-muted-foreground'
  return n > 0 ? 'text-up' : 'text-down'
}

function pnlSigned(v: string | number | null | undefined): string {
  if (v == null) return '-'
  const n = Number(v)
  if (isNaN(n)) return String(v)
  return `${n >= 0 ? '+' : ''}${fmtWan(v)}`
}

// ---------- 录入表单 ----------
const showAdd = ref(false)
const adding = ref(false)
const addError = ref('')
const form = ref({
  code: '',
  name: '',
  buy_price: '',
  shares: '',
  buy_date: '',
  note: '',
})

function resetForm() {
  form.value = { code: '', name: '', buy_price: '', shares: '', buy_date: '', note: '' }
  addError.value = ''
}

async function submitAdd() {
  if (!form.value.code.trim() || !form.value.buy_price.trim() || !form.value.shares.trim()) {
    addError.value = '请填写代码、买入价和股数'
    return
  }
  adding.value = true
  addError.value = ''
  try {
    await store.addPosition({
      code: form.value.code.trim(),
      name: form.value.name.trim() || undefined,
      buy_price: form.value.buy_price.trim(),
      shares: parseInt(form.value.shares.trim(), 10),
      buy_date: form.value.buy_date || undefined,
      note: form.value.note.trim() || undefined,
    })
    showAdd.value = false
    resetForm()
  } catch (e: any) {
    addError.value = '添加失败: ' + (e?.message || e)
  } finally {
    adding.value = false
  }
}

// ---------- 语音录入 ----------
const {
  state: voiceState,
  transcript,
  error: voiceError,
  start: voiceStart,
  stop: voiceStop,
  parse: voiceParse,
} = useSpeechRecognition()

const voiceSupported = typeof window !== 'undefined' &&
  ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

const showVoice = ref(false)
const voiceResult = ref<ReturnType<typeof voiceParse> | null>(null)

function startVoice() {
  voiceResult.value = null
  transcript.value = ''
  showVoice.value = true
  voiceStart()
}

function toggleVoice() {
  if (voiceState.value === 'listening') {
    voiceStop()
  } else {
    startVoice()
  }
}

function applyVoice() {
  const result = voiceParse(transcript.value)
  voiceResult.value = result
  if (result.code) form.value.code = result.code
  if (result.name) form.value.name = result.name
  if (result.price) form.value.buy_price = result.price
  if (result.shares) form.value.shares = result.shares
  showVoice.value = false
  showAdd.value = true
}

watch(voiceState, (s) => {
  if (s === 'done' && transcript.value) {
    voiceResult.value = voiceParse(transcript.value)
  }
})

// ---------- 持仓行展开 + 调仓 ----------
const expandedId = ref<number | null>(null)
const adjusting = ref(false)
const adjError = ref('')
const adjForm = ref({
  action: 'buy' as 'buy' | 'sell' | 'dividend',
  price: '',
  shares: '',
  note: '',
})

function resetAdj() {
  adjForm.value = { action: 'buy', price: '', shares: '', note: '' }
  adjError.value = ''
}

async function toggleExpand(p: PositionDetail) {
  if (expandedId.value === p.id) {
    expandedId.value = null
    return
  }
  expandedId.value = p.id
  resetAdj()
  if (!store.adjustmentsMap[p.id]) {
    await store.fetchAdjustments(p.id)
  }
}

async function submitAdjust(p: PositionDetail) {
  if (!adjForm.value.price.trim() || !adjForm.value.shares.trim()) {
    adjError.value = '请填写价格和股数'
    return
  }
  adjusting.value = true
  adjError.value = ''
  try {
    await store.addAdjustment(p.id, {
      action: adjForm.value.action,
      price: adjForm.value.price.trim(),
      shares: parseInt(adjForm.value.shares.trim(), 10),
      note: adjForm.value.note.trim() || undefined,
    })
    resetAdj()
  } catch (e: any) {
    adjError.value = '调仓失败: ' + (e?.message || e)
  } finally {
    adjusting.value = false
  }
}

async function removePosition(p: PositionDetail) {
  if (!confirm(`确认清仓「${p.name || p.code}」(${p.shares}股)?`)) return
  try {
    await store.removePosition(p.id)
    if (expandedId.value === p.id) expandedId.value = null
  } catch (e: any) {
    alert('删除失败: ' + (e?.message || e))
  }
}

// ---------- 调仓历史时间线辅助 ----------
function actionLabel(a: string): string {
  if (a === 'buy') return '加仓'
  if (a === 'sell') return '减仓'
  return '分红'
}

function actionBadgeClass(a: string): string {
  if (a === 'buy') return 'bg-up/10 text-up'
  if (a === 'sell') return 'bg-down/10 text-down'
  return 'bg-yellow-500/10 text-yellow-600'
}

function actionDotClass(a: string): string {
  if (a === 'buy') return 'bg-up'
  if (a === 'sell') return 'bg-down'
  return 'bg-yellow-500'
}

function fmtTimestamp(ts: string): string {
  return ts.slice(0, 16).replace('T', ' ')
}

function goDetail(code: string) {
  router.push({ name: 'detail', params: { code } })
}

// ---------- 生命周期 ----------
let refreshTimer: number | null = null

onMounted(() => {
  store.fetchAll()
  refreshTimer = window.setInterval(() => store.fetchAll(), 30_000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="mx-auto w-full max-w-5xl space-y-4 p-4 lg:p-6">
    <!-- 页头 -->
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold tracking-tight">💰 我的持仓</h1>
      <div class="flex items-center gap-2">
        <Button v-if="voiceSupported" variant="outline" size="sm" @click="toggleVoice">
          🎙️ 语音
        </Button>
        <Button size="sm" @click="showAdd = true">
          + 录入
        </Button>
      </div>
    </div>

    <!-- 总览卡片行 -->
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <!-- 骨架 -->
      <template v-if="loading && !summary">
        <Card v-for="i in 4" :key="i">
          <CardContent class="space-y-2">
            <Skeleton class="h-3 w-16" />
            <Skeleton class="h-7 w-24" />
          </CardContent>
        </Card>
      </template>

      <template v-else>
        <Card>
          <CardContent class="space-y-1">
            <p class="text-xs text-muted-foreground">总市值</p>
            <p class="font-mono text-2xl font-bold tabular-nums">
              {{ fmtWan(summary?.total_market_value) }}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent class="space-y-1">
            <p class="text-xs text-muted-foreground">总成本</p>
            <p class="font-mono text-2xl font-bold tabular-nums">
              {{ fmtWan(summary?.total_cost) }}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent class="space-y-1">
            <p class="text-xs text-muted-foreground">浮盈亏</p>
            <p class="font-mono text-2xl font-bold tabular-nums" :class="pnlClass(summary?.total_unrealized_pnl)">
              {{ pnlSigned(summary?.total_unrealized_pnl) }}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent class="space-y-1">
            <p class="text-xs text-muted-foreground">盈亏率</p>
            <p class="font-mono text-2xl font-bold tabular-nums" :class="pnlClass(summary?.total_unrealized_pnl_pct)">
              {{ fmtPct(summary?.total_unrealized_pnl_pct) }}
            </p>
          </CardContent>
        </Card>
      </template>
    </div>

    <!-- 持仓列表 -->
    <Card>
      <CardHeader class="flex flex-row items-center justify-between">
        <CardTitle class="text-base">持仓明细</CardTitle>
        <Badge variant="secondary" class="font-mono">{{ summary?.n_positions ?? 0 }}</Badge>
      </CardHeader>
      <Separator />
      <CardContent class="px-0">
        <!-- 空状态 -->
        <div
          v-if="!loading && positions.length === 0"
          class="flex flex-col items-center gap-3 py-12 text-sm text-muted-foreground"
        >
          <span>还没有持仓记录</span>
          <Button variant="outline" size="sm" @click="showAdd = true">
            录入第一笔持仓
          </Button>
        </div>

        <Table v-else>
          <TableHeader>
            <TableRow>
              <TableHead class="pl-6">名称 / 代码</TableHead>
              <TableHead class="text-right">成本</TableHead>
              <TableHead class="text-right">现价</TableHead>
              <TableHead class="text-right">股数</TableHead>
              <TableHead class="text-right">市值</TableHead>
              <TableHead class="text-right">浮盈亏</TableHead>
              <TableHead class="pr-6 text-center">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <template v-for="p in positions" :key="p.id">
              <TableRow
                class="cursor-pointer transition-colors hover:bg-muted/30"
                @click="toggleExpand(p)"
              >
                <TableCell class="pl-6">
                  <div class="font-medium text-card-foreground">{{ p.name || p.code }}</div>
                  <div class="font-mono text-[10px] text-muted-foreground">{{ p.code }}</div>
                </TableCell>
                <TableCell class="text-right font-mono text-sm tabular-nums">
                  {{ fmtPrice(p.avg_cost) }}
                </TableCell>
                <TableCell class="text-right font-mono text-sm tabular-nums" :class="pnlClass(p.unrealized_pnl)">
                  {{ p.current_price ? fmtPrice(p.current_price) : '-' }}
                </TableCell>
                <TableCell class="text-right font-mono text-sm tabular-nums">
                  {{ p.shares }}
                </TableCell>
                <TableCell class="text-right font-mono text-sm tabular-nums">
                  {{ fmtWan(p.market_value) }}
                </TableCell>
                <TableCell class="text-right">
                  <div class="font-mono text-sm font-bold tabular-nums" :class="pnlClass(p.unrealized_pnl)">
                    {{ pnlSigned(p.unrealized_pnl) }}
                  </div>
                  <div class="font-mono text-[10px] tabular-nums" :class="pnlClass(p.unrealized_pnl_pct)">
                    {{ fmtPct(p.unrealized_pnl_pct) }}
                  </div>
                </TableCell>
                <TableCell class="pr-6 text-center">
                  <div class="flex items-center justify-center gap-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-7 px-2"
                      @click.stop="goDetail(p.code)"
                    >
                      详情
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-7 px-2 text-muted-foreground hover:text-destructive"
                      @click.stop="removePosition(p)"
                    >
                      清仓
                    </Button>
                    <span
                      class="ml-1 text-xs text-muted-foreground transition-transform"
                      :class="expandedId === p.id ? 'rotate-90' : ''"
                    >
                      ›
                    </span>
                  </div>
                </TableCell>
              </TableRow>

              <!-- 展开行：调仓表单 + 历史 -->
              <TableRow v-if="expandedId === p.id" class="bg-muted/20 hover:bg-muted/20">
                <TableCell :colspan="7" class="p-4">
                  <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <!-- 调仓表单 -->
                    <div class="rounded-lg border border-border bg-card p-4">
                      <p class="mb-3 text-sm font-semibold">记录调仓</p>
                      <div class="space-y-3">
                        <div class="flex gap-2">
                          <Select v-model="adjForm.action">
                            <SelectTrigger class="w-28">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="buy">加仓</SelectItem>
                              <SelectItem value="sell">减仓</SelectItem>
                              <SelectItem value="dividend">分红</SelectItem>
                            </SelectContent>
                          </Select>
                          <Input
                            v-model="adjForm.price"
                            placeholder="价格"
                            inputmode="decimal"
                            class="flex-1"
                          />
                          <Input
                            v-model="adjForm.shares"
                            placeholder="股数"
                            inputmode="numeric"
                            class="flex-1"
                          />
                        </div>
                        <Input
                          v-model="adjForm.note"
                          placeholder="备注（可选）"
                        />
                        <p v-if="adjError" class="text-xs text-destructive">{{ adjError }}</p>
                        <Button
                          class="w-full"
                          size="sm"
                          :disabled="adjusting"
                          @click="submitAdjust(p)"
                        >
                          {{ adjusting ? '提交中…' : '提交调仓' }}
                        </Button>
                      </div>
                    </div>

                    <!-- 调仓历史时间线 -->
                    <div class="rounded-lg border border-border bg-card p-4">
                      <p class="mb-3 text-sm font-semibold text-muted-foreground">调仓历史</p>
                      <template v-if="store.adjustmentsMap[p.id]?.length">
                        <div class="space-y-0">
                          <div
                            v-for="(adj, idx) in store.adjustmentsMap[p.id]"
                            :key="adj.id"
                            class="relative flex gap-3 pb-4 last:pb-0"
                          >
                            <!-- 竖线 -->
                            <span
                              v-if="idx < (store.adjustmentsMap[p.id]?.length ?? 0) - 1"
                              class="absolute left-[5px] top-3 bottom-0 w-0.5 bg-border"
                            />
                            <span
                              class="mt-1 size-3 shrink-0 rounded-full"
                              :class="actionDotClass(adj.action)"
                            />
                            <div class="min-w-0 flex-1">
                              <div class="flex items-center gap-2">
                                <Badge
                                  variant="secondary"
                                  :class="cn('text-xs', actionBadgeClass(adj.action))"
                                >
                                  {{ actionLabel(adj.action) }}
                                </Badge>
                                <span class="font-mono text-sm font-semibold tabular-nums">
                                  {{ fmtPrice(adj.price) }} × {{ adj.shares }}股
                                </span>
                              </div>
                              <div class="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                                <span class="font-mono">{{ fmtTimestamp(adj.timestamp) }}</span>
                                <span v-if="adj.note">· {{ adj.note }}</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      </template>
                      <p v-else class="py-4 text-center text-xs text-muted-foreground">
                        暂无调仓记录
                      </p>
                    </div>
                  </div>
                </TableCell>
              </TableRow>
            </template>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <!-- 录入表单 Dialog -->
    <Dialog :open="showAdd" @update:open="(v: boolean) => (showAdd = v)">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>录入买入</DialogTitle>
          <DialogDescription>填写股票代码、买入价和股数</DialogDescription>
        </DialogHeader>
        <div class="space-y-3">
          <div class="flex gap-2">
            <Input
              v-model="form.code"
              placeholder="代码（600519）"
              inputmode="numeric"
              maxlength="6"
            />
            <Input
              v-model="form.name"
              placeholder="名称（可选）"
            />
          </div>
          <div class="flex gap-2">
            <Input
              v-model="form.buy_price"
              placeholder="买入价"
              inputmode="decimal"
            />
            <Input
              v-model="form.shares"
              placeholder="股数"
              inputmode="numeric"
            />
          </div>
          <div class="flex gap-2">
            <Input v-model="form.buy_date" type="date" />
            <Input v-model="form.note" placeholder="备注（可选）" />
          </div>
          <p v-if="addError" class="text-xs text-destructive">{{ addError }}</p>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showAdd = false">取消</Button>
          <Button :disabled="adding" @click="submitAdd">
            {{ adding ? '保存中…' : '保存' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 语音录入 Dialog -->
    <Dialog :open="showVoice" @update:open="(v: boolean) => (showVoice = v)">
      <DialogContent class="max-w-sm">
        <DialogHeader>
          <DialogTitle>🎙️ 语音录入</DialogTitle>
          <DialogDescription>说出股票信息，自动填入表单</DialogDescription>
        </DialogHeader>
        <div class="flex flex-col items-center gap-3 py-2">
          <button
            class="flex size-16 items-center justify-center rounded-full border transition-[color,background-color,border-color,box-shadow,transform]"
            :class="voiceState === 'listening'
              ? 'border-up bg-up/10 animate-pulse'
              : 'border-border bg-muted/50 hover:bg-muted'"
            @click="toggleVoice"
          >
            <span class="text-2xl">{{ voiceState === 'listening' ? '🔴' : '🎙️' }}</span>
          </button>
          <p class="text-sm text-muted-foreground">
            <span v-if="voiceState === 'listening'">正在听…</span>
            <span v-else-if="voiceState === 'done'">识别完成</span>
            <span v-else-if="voiceState === 'error'" class="text-destructive">{{ voiceError }}</span>
            <span v-else>点击麦克风开始说话</span>
          </p>
          <div v-if="transcript" class="w-full rounded-md bg-muted/50 px-3 py-2 text-sm">
            "{{ transcript }}"
          </div>
          <div v-if="voiceResult" class="w-full space-y-1 rounded-md border border-border p-3 text-sm">
            <div v-if="voiceResult.code" class="flex justify-between">
              <span class="text-muted-foreground">代码</span><span class="font-mono">{{ voiceResult.code }}</span>
            </div>
            <div v-if="voiceResult.name" class="flex justify-between">
              <span class="text-muted-foreground">名称</span><span>{{ voiceResult.name }}</span>
            </div>
            <div v-if="voiceResult.price" class="flex justify-between">
              <span class="text-muted-foreground">买入价</span><span class="font-mono">{{ voiceResult.price }}</span>
            </div>
            <div v-if="voiceResult.shares" class="flex justify-between">
              <span class="text-muted-foreground">股数</span><span class="font-mono">{{ voiceResult.shares }}</span>
            </div>
          </div>
          <p class="text-xs text-muted-foreground">
            试试说："贵州茅台 600519 买入价1680 100股"
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showVoice = false">取消</Button>
          <Button :disabled="!transcript" @click="applyVoice">填入表单</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
