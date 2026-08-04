<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import {
  Bot,
  CheckCircle2,
  FileText,
  Mic,
  MicOff,
  Plus,
  RotateCcw,
  Send,
  Square,
  Target,
  User,
  Wrench,
} from 'lucide-vue-next'
import { agentRoute, agentStream, getAgentHistory } from '@/api/agent'
import type {
  AgentPageContext,
  AgentStreamState,
  PredictionsCreatedEvent,
  ToolCallEvent,
  ToolResultEvent,
} from '@/api/agent'
import { getSnapshot } from '@/api/index'
import { getIndexes } from '@/api/market'
import { getPredictions } from '@/api/predictions'
import { recentSignals } from '@/api/signals'
import { resetChatSessionId } from '@/api/client'
import type { IndexQuote, Prediction, StockSearchResult } from '@/api/types'
import { useSpeechRecognition } from '@/composables/useSpeechRecognition'
import { fmtPct, fmtPrice } from '@/utils/format'
import ContextPanel from '@/components/ContextPanel.vue'
import BrandMark from '@/components/BrandMark.vue'
import StockSearch from '@/components/StockSearch.vue'
import ToolRow from '@/components/chat/ToolRow.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

marked.setOptions({ breaks: true, gfm: true })

interface ToolEvent {
  tool: string
  args?: Record<string, unknown>
  status: 'running' | 'done' | 'fail'
  result?: string
  elapsedMs?: number
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  toolsUsed?: string[]
  rounds?: number
  steps?: string[]
  workflowId?: string
  toolEvents?: ToolEvent[]
  /** 本轮 done 之后由后台记忆抽取创建的预测（WS predictions_created） */
  predictionsCreated?: PredictionsCreatedEvent
  streaming?: boolean
  error?: boolean
}

const route = useRoute()
const router = useRouter()
const messages = ref<Message[]>([])
const input = ref('')
const loading = ref(false)
const queuedMessages = ref<string[]>([])
const contextOpen = ref(false)
const scrollContainerRef = ref<HTMLElement>()
const composerRef = ref<HTMLTextAreaElement>()
const userScrolledUp = ref(false)
const stream = ref<ReturnType<typeof agentStream> | null>(null)
const lastFailedMessage = ref('')
const connectionState = ref<AgentStreamState | 'idle'>('idle')
const agentAvailable = ref<boolean | null>(null)
const indexes = ref<IndexQuote[]>([])
const watchlistUp = ref(0)
const watchlistDown = ref(0)
const signalCount = ref(0)
const recentPredictions = ref<Prediction[]>([])
type AgentStreamClient = ReturnType<typeof agentStream>

let activeRequestId = 0
let activeAssistantIdx: number | null = null
let routeAbortController: AbortController | null = null
/** 已完成回答仍保留各自的连接，等待后台预测附件；不能被下一轮提前关闭。 */
const retainedStreams = new Set<AgentStreamClient>()
const retainedStreamTimers = new Map<AgentStreamClient, number>()

const CHAT_STORAGE_KEY = 'mommy_chat_messages_v1'
const CHAT_DRAFT_KEY = 'mommy_chat_draft_v1'

const activePageContext = computed<AgentPageContext | undefined>(() => {
  const stockCode = typeof route.query.stock === 'string' ? route.query.stock : ''
  const tab = typeof route.query.tab === 'string' ? route.query.tab : 'overview'
  if (!/^\d{6}$/.test(stockCode) || !['overview', 'chart', 'flow', 'decisions'].includes(tab)) {
    return undefined
  }
  const basketId = typeof route.query.basket === 'string'
    && /^(theme|group):[A-Za-z0-9_-]+$/.test(route.query.basket)
    ? route.query.basket
    : undefined
  const quoteAsOf = typeof route.query.as_of === 'string'
    && !Number.isNaN(Date.parse(route.query.as_of))
    ? route.query.as_of
    : undefined
  return {
    surface: 'stock',
    stock_code: stockCode,
    tab: tab as AgentPageContext['tab'],
    basket_id: basketId,
    quote_as_of: quoteAsOf,
  }
})

const pageContextLabel = computed(() => {
  const context = activePageContext.value
  if (!context) return ''
  const tabLabels: Record<AgentPageContext['tab'], string> = {
    overview: '概览',
    chart: '走势',
    flow: '资金',
    decisions: '决策记录',
  }
  const name = typeof route.query.stock_name === 'string'
    ? route.query.stock_name
    : context.stock_code
  return `${name} · ${tabLabels[context.tab]}`
})

const quickQuestions = [
  '今天怎么样？',
  '大盘怎么样？',
  '主力在买什么？',
  '我的持仓怎么样？',
  '半导体板块怎么样',
  '今日总结',
]

const workflowLabels: Record<string, string> = {
  morning_brief: '早安简报',
  stock_analysis: '个股分析',
  sector_scan: '板块扫描',
  portfolio_review: '持仓复盘',
  money_flow_scan: '资金流扫描',
  daily_summary: '今日总结',
}

const speech = useSpeechRecognition()
const speechSupported = speech.isSupported()

const wsStatusText = computed(() => {
  if (agentAvailable.value === false) return 'AI 未配置'
  if (connectionState.value === 'connected') return loading.value ? '回答中…' : '已连接'
  if (connectionState.value === 'connecting') return '连接中…'
  if (connectionState.value === 'disconnected') return '已断开'
  return '服务就绪'
})

const wsDotColor = computed(() => {
  if (agentAvailable.value === false || connectionState.value === 'disconnected') return 'bg-muted-foreground'
  if (connectionState.value === 'connected') return 'bg-green-500'
  if (connectionState.value === 'connecting') return 'bg-yellow-500'
  return 'bg-green-500/70'
})

const stockQuery = computed(() => {
  const match = input.value.match(/@([^@\s]*)$/)
  return match ? match[1] : null
})

function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text) as string, {
    USE_PROFILES: { html: true },
  })
}

/** 预测附件深链：全部预测同一只股时带 ?code= 过滤，否则进总列表 */
function predictionLinkTarget(message: Message): string {
  const created = message.predictionsCreated
  if (!created || created.predictions.length === 0) return '/predictions'
  const codes = new Set(created.predictions.map((p) => p.code))
  return codes.size === 1
    ? `/predictions?code=${encodeURIComponent(created.predictions[0]!.code)}`
    : '/predictions'
}

function predictionLinkLabel(message: Message): string {
  return message.predictionsCreated
    ? `查看预测记录（${message.predictionsCreated.count}）`
    : '查看预测跟踪'
}

function scrollToBottom(force = false) {
  nextTick(() => {
    if (userScrolledUp.value && !force) return
    scrollContainerRef.value?.scrollTo({
      top: scrollContainerRef.value.scrollHeight,
      behavior: 'smooth',
    })
  })
}

function onScroll(event: Event) {
  const target = event.target as HTMLElement
  const distance = target.scrollHeight - target.scrollTop - target.clientHeight
  userScrolledUp.value = distance > 100
}

function resizeComposer() {
  nextTick(() => {
    const element = composerRef.value
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`
  })
}

function processNextQueued() {
  const next = queuedMessages.value.shift()
  if (next) window.setTimeout(() => void sendNow(next), 0)
}

function closeStreamClient(client: AgentStreamClient) {
  const timer = retainedStreamTimers.get(client)
  if (timer != null) {
    window.clearTimeout(timer)
    retainedStreamTimers.delete(client)
  }
  retainedStreams.delete(client)
  if (stream.value === client) stream.value = null
  client.close()
}

/** 立即关闭当前仍在生成的流；已完成轮次的附件连接不受影响。 */
function closeActiveStream() {
  const active = stream.value
  if (active) closeStreamClient(active)
}

function closeAllStreams() {
  const clients = new Set(retainedStreams)
  if (stream.value) clients.add(stream.value)
  for (const client of clients) closeStreamClient(client)
}

/**
 * done 之后后台记忆抽取可能再推 predictions_created，
 * 每个已完成轮次分别保留一个到达窗口；只有新建对话/卸载会统一关闭。
 */
function scheduleStreamClose(client: AgentStreamClient) {
  const existing = retainedStreamTimers.get(client)
  if (existing != null) window.clearTimeout(existing)
  retainedStreams.add(client)
  if (stream.value === client) stream.value = null
  const timer = window.setTimeout(() => {
    closeStreamClient(client)
  }, 60_000)
  retainedStreamTimers.set(client, timer)
}

function finishTurn() {
  loading.value = false
  activeAssistantIdx = null
  const finishedStream = stream.value
  if (finishedStream) scheduleStreamClose(finishedStream)
  scrollToBottom()
  processNextQueued()
}

function stopGeneration() {
  const assistantIdx = activeAssistantIdx
  activeRequestId += 1
  routeAbortController?.abort()
  routeAbortController = null
  closeActiveStream()
  connectionState.value = 'idle'
  loading.value = false
  activeAssistantIdx = null
  if (assistantIdx != null) {
    const assistant = messages.value[assistantIdx]
    if (assistant?.streaming) {
      assistant.streaming = false
      assistant.content = assistant.content
        ? `${assistant.content}\n\n（已停止）`
        : '（已停止）'
    }
  }
  processNextQueued()
}

function submit(message: string) {
  const text = message.trim()
  if (!text) return
  input.value = ''
  if (loading.value) {
    queuedMessages.value.push(text)
    return
  }
  void sendNow(text)
}

async function sendNow(text: string) {
  const requestId = ++activeRequestId
  lastFailedMessage.value = ''
  routeAbortController?.abort()
  routeAbortController = null
  closeActiveStream()
  connectionState.value = 'idle'

  messages.value.push({ role: 'user', content: text })
  loading.value = true
  const assistantIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  activeAssistantIdx = assistantIdx
  scrollToBottom(true)

  const routeController = new AbortController()
  routeAbortController = routeController
  try {
    const response = activePageContext.value
      ? { matched: false }
      : await agentRoute(text, routeController.signal)
    if (requestId !== activeRequestId) return
    if (response.matched && response.reply) {
      messages.value[assistantIdx] = {
        role: 'assistant',
        content: response.reply,
        workflowId: response.workflow_id,
        steps: response.steps?.filter((step) => step.success).map((step) => step.name),
        streaming: false,
      }
      finishTurn()
      return
    }
  } catch {
    if (requestId !== activeRequestId) return
  } finally {
    if (routeAbortController === routeController) routeAbortController = null
  }

  if (requestId !== activeRequestId) return
  const history = messages.value
    .slice(Math.max(0, messages.value.length - 22), -2)
    .map((message) => ({ role: message.role, content: message.content }))
  let currentText = ''

  stream.value = agentStream(
    (chunk) => {
      if (requestId !== activeRequestId) return
      currentText += chunk
      messages.value[assistantIdx].content = currentText
      scrollToBottom()
    },
    (doneText, toolsUsed, rounds) => {
      if (requestId !== activeRequestId) return
      if (!currentText && doneText) messages.value[assistantIdx].content = doneText
      const content = messages.value[assistantIdx].content
      if (content.includes('AI 助手未配置')) agentAvailable.value = false
      else agentAvailable.value = true
      messages.value[assistantIdx].toolsUsed = toolsUsed
      messages.value[assistantIdx].rounds = rounds
      messages.value[assistantIdx].streaming = false
      finishTurn()
    },
    () => {
      if (requestId !== activeRequestId) return
      messages.value[assistantIdx].content = ''
    },
    (message) => {
      if (requestId !== activeRequestId) return
      messages.value[assistantIdx].content = message
      messages.value[assistantIdx].error = true
      messages.value[assistantIdx].streaming = false
      connectionState.value = 'disconnected'
      lastFailedMessage.value = text
      finishTurn()
    },
    (state) => {
      if (requestId === activeRequestId) connectionState.value = state
    },
    (event: ToolCallEvent) => {
      if (requestId !== activeRequestId) return
      const assistant = messages.value[assistantIdx]
      assistant.toolEvents ??= []
      assistant.toolEvents.push({
        tool: event.tool,
        args: event.args,
        status: 'running',
      })
      scrollToBottom()
    },
    (event: ToolResultEvent) => {
      if (requestId !== activeRequestId) return
      const assistant = messages.value[assistantIdx]
      assistant.toolEvents ??= []
      const runningEvent = [...assistant.toolEvents]
        .reverse()
        .find((item) => item.tool === event.tool && item.status === 'running')
      if (runningEvent) {
        runningEvent.status = event.status
        runningEvent.result = event.result
        runningEvent.elapsedMs = event.elapsedMs
      } else {
        assistant.toolEvents.push({
          tool: event.tool,
          status: event.status,
          result: event.result,
          elapsedMs: event.elapsedMs,
        })
      }
      scrollToBottom()
    },
    (event: PredictionsCreatedEvent) => {
      // 已完成轮次允许在后续轮次开始后继续接收自己的后台附件；连接本身
      // 与 assistantIdx 一一对应，新建对话/卸载时会统一关闭这些连接。
      const assistant = messages.value[assistantIdx]
      if (assistant && assistant.role === 'assistant') {
        assistant.predictionsCreated = event
        scrollToBottom()
      }
    },
  )
  stream.value.send(text, history, activePageContext.value)
}

async function clearPageContext() {
  const {
    stock: _stock,
    stock_name: _name,
    tab: _tab,
    basket: _basket,
    as_of: _asOf,
    ...remainingQuery
  } = route.query
  await router.replace({ query: remainingQuery })
  composerRef.value?.focus()
}

function onComposerKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit(input.value)
  }
}

function retry() {
  if (!lastFailedMessage.value) return
  const last = messages.value.at(-1)
  if (last?.role === 'assistant' && last.error) messages.value.pop()
  const failed = lastFailedMessage.value
  lastFailedMessage.value = ''
  submit(failed)
}

function startNewConversation() {
  queuedMessages.value = []
  stopGeneration()
  closeAllStreams()
  resetChatSessionId()
  messages.value = []
  input.value = ''
  lastFailedMessage.value = ''
  try {
    window.sessionStorage.removeItem(CHAT_STORAGE_KEY)
    window.sessionStorage.removeItem(CHAT_DRAFT_KEY)
  } catch {
    // The fresh in-memory conversation still works without storage.
  }
  composerRef.value?.focus()
}

function selectStock(stock: StockSearchResult) {
  input.value = input.value.replace(/@[^@\s]*$/, `@${stock.name || stock.code}（${stock.code}） `)
  composerRef.value?.focus()
}

function toggleSpeech() {
  if (speech.state.value === 'listening') speech.stop()
  else speech.start()
}

function restoreLocalConversation(): boolean {
  try {
    const saved = window.sessionStorage.getItem(CHAT_STORAGE_KEY)
    if (saved) {
      const parsed = JSON.parse(saved) as unknown
      if (Array.isArray(parsed)) {
        messages.value = parsed
          .filter(
            (item): item is Message =>
              typeof item === 'object' &&
              item !== null &&
              ((item as Message).role === 'user' || (item as Message).role === 'assistant') &&
              typeof (item as Message).content === 'string',
          )
          .slice(-40)
          .map((item) => ({ ...item, streaming: false }))
      }
    }
    input.value = window.sessionStorage.getItem(CHAT_DRAFT_KEY) ?? ''
  } catch {
    return false
  }
  return messages.value.length > 0
}

async function restoreServerConversation() {
  try {
    const history = await getAgentHistory(40)
    if (messages.value.length === 0) {
      messages.value = history.map((item) => ({ role: item.role, content: item.content }))
    }
  } catch {
    // A local-only conversation remains available when history cannot load.
  }
}

async function loadWelcomeOverview() {
  const [indexResult, snapshotResult, signalsResult, predictionResult] = await Promise.allSettled([
    getIndexes(),
    getSnapshot(),
    recentSignals(),
    getPredictions(3),
  ])
  if (indexResult.status === 'fulfilled') indexes.value = indexResult.value.slice(0, 3)
  if (snapshotResult.status === 'fulfilled') {
    watchlistUp.value = snapshotResult.value.n_up
    watchlistDown.value = snapshotResult.value.n_down
  }
  if (signalsResult.status === 'fulfilled') signalCount.value = signalsResult.value.length
  if (predictionResult.status === 'fulfilled') recentPredictions.value = predictionResult.value
}

async function consumeQuery() {
  const query = route.query.q
  if (typeof query !== 'string' || !query.trim()) return
  const { q: _query, ...remainingQuery } = route.query
  await router.replace({ query: remainingQuery })
  submit(query)
}

watch(input, (value) => {
  resizeComposer()
  try {
    if (value) window.sessionStorage.setItem(CHAT_DRAFT_KEY, value)
    else window.sessionStorage.removeItem(CHAT_DRAFT_KEY)
  } catch {
    // Keep the live draft in memory.
  }
})

watch(
  messages,
  (value) => {
    try {
      const snapshot = value.slice(-40).map((message) => ({
        ...message,
        content: message.content.slice(0, 20_000),
        streaming: false,
      }))
      window.sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(snapshot))
    } catch {
      // Keep the live conversation in memory.
    }
  },
  { deep: true },
)

watch(speech.transcript, (value) => {
  if (value) input.value = value
})

onMounted(async () => {
  const restored = restoreLocalConversation()
  if (!restored) await restoreServerConversation()
  await Promise.all([loadWelcomeOverview(), consumeQuery()])
  resizeComposer()
})

onUnmounted(() => {
  activeRequestId += 1
  routeAbortController?.abort()
  closeAllStreams()
  speech.stop()
})
</script>

<template>
  <div class="flex h-[calc(100dvh-var(--mobile-nav-height))] bg-muted/30 md:h-dvh">
    <section class="flex min-w-0 flex-1 flex-col" aria-label="AI 对话">
      <header class="flex shrink-0 items-center gap-2 border-b bg-card px-3 py-2.5 sm:px-4">
        <BrandMark alt="妈妈炒股老奶奶 Logo" size="sm" />
        <div class="min-w-0">
          <h1 class="truncate text-sm font-semibold sm:text-base">投研对话</h1>
          <span class="flex items-center gap-1 text-[11px] text-muted-foreground" role="status" aria-live="polite">
            <span class="size-1.5 rounded-full" :class="wsDotColor" />
            {{ wsStatusText }}
          </span>
        </div>
        <div class="ml-auto flex items-center gap-1">
          <Dialog v-model:open="contextOpen">
            <DialogTrigger as-child>
              <Button variant="ghost" size="sm" class="gap-1 xl:hidden" aria-label="打开投研上下文">
                <FileText class="size-4" aria-hidden="true" />
                <span class="hidden sm:inline">上下文</span>
              </Button>
            </DialogTrigger>
            <DialogContent class="left-auto right-0 top-0 z-[60] h-dvh w-[88vw] max-w-sm translate-x-0 translate-y-0 gap-0 rounded-none bg-background p-0 xl:hidden">
              <DialogTitle class="sr-only">投研上下文</DialogTitle>
              <DialogDescription class="sr-only">查看自选股、近期预测与最新信号</DialogDescription>
              <ContextPanel />
            </DialogContent>
          </Dialog>
          <Button variant="ghost" size="sm" class="gap-1" @click="startNewConversation">
            <Plus class="size-4" aria-hidden="true" />
            <span class="hidden sm:inline">新对话</span>
          </Button>
        </div>
      </header>

      <div
        v-if="agentAvailable === false"
        role="alert"
        class="border-b bg-muted px-4 py-2 text-center text-xs text-muted-foreground"
      >
        AI 未配置：对话回答不可用，行情与持仓数据仍可正常浏览。
      </div>

      <div
        v-if="activePageContext"
        role="status"
        class="flex shrink-0 items-center gap-2 border-b bg-primary/5 px-4 py-2 text-xs"
      >
        <span class="truncate">正在结合：{{ pageContextLabel }}</span>
        <button
          type="button"
          class="ml-auto min-h-8 shrink-0 rounded-md px-2 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          aria-label="退出当前个股上下文"
          @click="clearPageContext"
        >退出上下文</button>
      </div>

      <div class="relative min-h-0 flex-1">
        <div ref="scrollContainerRef" class="h-full overflow-y-auto" :aria-busy="loading" @scroll="onScroll">
          <div class="mx-auto w-full max-w-3xl space-y-5 px-3 py-5 sm:px-5">
            <section v-if="messages.length === 0" class="space-y-4" aria-labelledby="welcome-title">
              <div class="rounded-2xl border bg-card p-4 shadow-sm sm:p-5">
                <Badge variant="secondary" class="mb-3">今天的投研从这里开始</Badge>
                <h2 id="welcome-title" class="text-xl font-bold">你问判断，我给证据。</h2>
                <p class="mt-2 text-sm text-muted-foreground">我会记住自己的判断，并在行情变化后回来验证。</p>

                <div class="mt-4 grid grid-cols-3 gap-2">
                  <div v-for="index in indexes" :key="index.code" class="rounded-xl bg-muted/60 p-2.5">
                    <p class="truncate text-[11px] text-muted-foreground">{{ index.name }}</p>
                    <p class="mt-1 font-mono text-sm font-semibold">{{ fmtPrice(index.price) }}</p>
                    <p class="font-mono text-xs" :class="Number(index.change_pct) >= 0 ? 'text-up' : 'text-down'">{{ fmtPct(index.change_pct) }}</p>
                  </div>
                  <div v-if="indexes.length === 0" class="col-span-3 rounded-xl bg-muted/60 p-3 text-xs text-muted-foreground">指数概览暂不可用，仍可直接提问。</div>
                </div>

                <div class="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <span class="rounded-full bg-muted px-2.5 py-1">自选上涨 {{ watchlistUp }}</span>
                  <span class="rounded-full bg-muted px-2.5 py-1">自选下跌 {{ watchlistDown }}</span>
                  <span class="rounded-full bg-muted px-2.5 py-1">最新信号 {{ signalCount }}</span>
                  <button type="button" class="rounded-full bg-primary/10 px-2.5 py-1 text-primary hover:bg-primary/15" @click="contextOpen = true">
                    近期预测 {{ recentPredictions.length }}
                  </button>
                </div>
              </div>

              <div class="flex flex-wrap gap-2">
                <button
                  v-for="question in quickQuestions"
                  :key="question"
                  type="button"
                  class="min-h-10 rounded-full border bg-card px-3 text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  @click="submit(question)"
                >
                  {{ question }}
                </button>
              </div>
            </section>

            <article
              v-for="(message, index) in messages"
              :key="index"
              :class="cn('flex gap-3', message.role === 'user' ? 'flex-row-reverse' : 'flex-row')"
            >
              <div :class="cn('flex size-8 shrink-0 items-center justify-center rounded-full', message.role === 'user' ? 'bg-primary text-primary-foreground' : 'border bg-card text-muted-foreground')">
                <User v-if="message.role === 'user'" class="size-4" aria-hidden="true" />
                <Bot v-else class="size-4" aria-hidden="true" />
              </div>
              <div :class="cn('flex min-w-0 max-w-[86%] flex-col gap-1.5 sm:max-w-[80%]', message.role === 'user' ? 'items-end' : 'items-start')">
                <Badge v-if="message.workflowId" variant="outline" class="text-[10px]">
                  {{ workflowLabels[message.workflowId] || message.workflowId }}
                </Badge>
                <template v-if="message.role === 'assistant'">
                  <ToolRow
                    v-for="(event, eventIndex) in message.toolEvents ?? []"
                    :key="`${event.tool}-${eventIndex}`"
                    :tool="event.tool"
                    :args="event.args"
                    :status="event.status"
                    :result="event.result"
                    :error="event.status === 'fail' ? event.result : undefined"
                    :elapsed-ms="event.elapsedMs"
                  />
                </template>
                <div :class="cn('rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed', message.role === 'user' ? 'rounded-tr-sm bg-primary text-primary-foreground' : message.error ? 'rounded-tl-sm border border-destructive/30 bg-destructive/5 text-foreground' : 'rounded-tl-sm border bg-card text-card-foreground')">
                  <div v-if="message.content" class="markdown-body break-words" v-html="renderMarkdown(message.content)" />
                  <div v-else-if="message.streaming" class="flex items-center gap-1 py-1" role="status" aria-label="AI 正在思考">
                    <span v-for="dot in 3" :key="dot" class="size-1.5 animate-pulse rounded-full bg-muted-foreground" :style="{ animationDelay: `${dot * 120}ms` }" />
                  </div>
                </div>
                <div v-if="message.toolsUsed?.length && !message.toolEvents?.length" class="flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
                  <Wrench class="size-3" aria-hidden="true" />
                  <span>{{ message.toolsUsed.join(' · ') }}</span>
                  <CheckCircle2 class="size-3 text-green-600" aria-hidden="true" />
                  <span v-if="message.rounds">{{ message.rounds }} 轮</span>
                </div>
                <div v-if="message.steps?.length" class="flex flex-wrap gap-1">
                  <Badge v-for="step in message.steps" :key="step" variant="secondary" class="text-[10px]">{{ step }}</Badge>
                </div>
                <Button v-if="message.error && index === messages.length - 1" variant="outline" size="sm" class="gap-1" @click="retry">
                  <RotateCcw class="size-3.5" aria-hidden="true" />重试
                </Button>
                <RouterLink
                  v-if="message.role === 'assistant' && !message.streaming && !message.error"
                  :to="predictionLinkTarget(message)"
                  class="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <Target class="size-3.5" aria-hidden="true" />{{ predictionLinkLabel(message) }}
                </RouterLink>
              </div>
            </article>
          </div>
        </div>
      </div>

      <footer class="shrink-0 border-t bg-card p-3 sm:p-4">
        <div class="relative mx-auto max-w-3xl">
          <div v-if="stockQuery !== null" class="absolute inset-x-0 bottom-full z-40 mb-2 rounded-lg bg-card shadow-lg">
            <StockSearch :model-value="stockQuery" aria-label="@ 股票联想" @select="selectStock" />
          </div>
          <div class="flex items-end gap-2 rounded-2xl border bg-background p-2 shadow-sm focus-within:ring-2 focus-within:ring-primary/40">
            <Button
              v-if="speechSupported"
              type="button"
              variant="ghost"
              size="icon"
              :aria-label="speech.state.value === 'listening' ? '停止语音输入' : '开始语音输入'"
              :aria-pressed="speech.state.value === 'listening'"
              @click="toggleSpeech"
            >
              <MicOff v-if="speech.state.value === 'listening'" class="size-4 text-destructive" aria-hidden="true" />
              <Mic v-else class="size-4" aria-hidden="true" />
            </Button>
            <textarea
              ref="composerRef"
              v-model="input"
              rows="1"
              aria-label="输入投研问题"
              placeholder="问行情、个股、板块或持仓…（@ 搜股票）"
              class="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-1 py-2 text-sm outline-none placeholder:text-muted-foreground"
              @keydown="onComposerKeydown"
            />
            <Button v-if="loading" type="button" size="icon" variant="destructive" aria-label="停止生成" @click="stopGeneration">
              <Square class="size-4" aria-hidden="true" />
            </Button>
            <Button v-else type="button" size="icon" :disabled="!input.trim()" aria-label="发送消息" @click="submit(input)">
              <Send class="size-4" aria-hidden="true" />
            </Button>
          </div>
          <div class="mt-1.5 flex min-h-4 items-center justify-between px-1 text-[11px] text-muted-foreground">
            <span>{{ speech.error.value || 'Enter 发送 · Shift+Enter 换行' }}</span>
            <span v-if="queuedMessages.length" role="status">已排队 {{ queuedMessages.length }} 条</span>
          </div>
        </div>
      </footer>
    </section>

    <div class="hidden w-80 shrink-0 border-l xl:block">
      <ContextPanel />
    </div>
  </div>
</template>

<style scoped>
.markdown-body :deep(p) { margin: 0.35em 0; }
.markdown-body :deep(p:first-child) { margin-top: 0; }
.markdown-body :deep(p:last-child) { margin-bottom: 0; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) { margin: 0.4em 0; padding-left: 1.25em; }
.markdown-body :deep(ul) { list-style: disc; }
.markdown-body :deep(ol) { list-style: decimal; }
.markdown-body :deep(code) { border-radius: 0.25rem; background: hsl(var(--muted)); padding: 0.1em 0.3em; font-size: 0.9em; }
.markdown-body :deep(pre) { overflow-x: auto; border-radius: 0.5rem; background: hsl(var(--muted)); padding: 0.75rem; }
.markdown-body :deep(pre code) { padding: 0; background: transparent; }
.markdown-body :deep(table) { margin: 0.5em 0; border-collapse: collapse; font-size: 0.875em; }
.markdown-body :deep(th),
.markdown-body :deep(td) { border: 1px solid hsl(var(--border)); padding: 0.25em 0.5em; }
</style>
