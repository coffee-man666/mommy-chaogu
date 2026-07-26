<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { agentStream, agentRoute } from '@/api/agent'
import type { AgentStreamState } from '@/api/agent'
import { Button } from '@/components/ui/button'
import { ArrowDown } from 'lucide-vue-next'
import StatusBar from '@/components/chat/StatusBar.vue'
import MessageBubble from '@/components/chat/MessageBubble.vue'
import ToolRow from '@/components/chat/ToolRow.vue'
import WorkflowCard from '@/components/chat/WorkflowCard.vue'
import type { WorkflowStep } from '@/components/chat/WorkflowCard.vue'
import WorkingIndicator from '@/components/chat/WorkingIndicator.vue'
import InputBar from '@/components/chat/InputBar.vue'
import { randomVerb } from '@/lib/workingVerbs'
import { toolDisplayName } from '@/lib/toolNames'

marked.setOptions({ breaks: true, gfm: true })

interface Message {
  role: 'user' | 'assistant'
  content: string
  toolsUsed?: string[]
  steps?: string[]
  stepsRaw?: { name: string; success: boolean }[]
  workflowId?: string
  streaming?: boolean
  error?: boolean
}

const route = useRoute()
const router = useRouter()
const messages = ref<Message[]>([])
const input = ref('')
const loading = ref(false)
const scrollContainerRef = ref<HTMLElement>()
const userScrolledUp = ref(false)
const stream = ref<ReturnType<typeof agentStream> | null>(null)
const lastFailedMessage = ref('')
let activeRequestId = 0
let activeAssistantIdx: number | null = null
let routeAbortController: AbortController | null = null

// Kimi 风工作指示
const currentVerb = ref(randomVerb())
const turnStart = ref(0)
const nowTick = ref(0) // 触发 WorkingIndicator 耗时刷新
let nowTimer: number | null = null

const CHAT_STORAGE_KEY = 'mommy_chat_messages_v1'
const CHAT_DRAFT_KEY = 'mommy_chat_draft_v1'
const connectionState = ref<AgentStreamState | 'idle'>('idle')

const wsStatus = computed(() => connectionState.value)

const wsDotColor = computed(() => {
  switch (wsStatus.value) {
    case 'connected':
      return 'bg-green-500'
    case 'disconnected':
      return 'bg-red-500'
    case 'idle':
      return 'bg-muted-foreground/60'
    default:
      return 'bg-yellow-500'
  }
})

const connectionLevel = computed<'live' | 'degraded' | 'offline' | 'idle'>(() => {
  switch (wsStatus.value) {
    case 'connected':
      return 'live'
    case 'disconnected':
      return 'offline'
    case 'idle':
      return 'idle'
    default:
      return 'degraded'
  }
})

const turnElapsedMs = computed(() => (turnStart.value ? Math.max(0, nowTick.value - turnStart.value) : 0))

/** 把 RouteStep[] 转成 WorkflowCard 需要的 WorkflowStep[]。
 *  后端 RouteStep 只有 success 布尔；没有 running 信息，已完成的标 ok，其余标 todo。 */
function toWorkflowSteps(steps: { name: string; success: boolean }[] | undefined): WorkflowStep[] {
  if (!steps) return []
  return steps.map((s) => ({
    display_name: s.name,
    status: s.success ? 'ok' : 'fail',
  }))
}

const wsStatusText = computed(() => {
  switch (wsStatus.value) {
    case 'connected':
      return loading.value ? '回答中…' : '已连接'
    case 'disconnected':
      return '已断开'
    case 'idle':
      return '就绪'
    default:
      return '连接中…'
  }
})

// 快捷问题 — 按场景分组
const quickQuestions = [
  '今天怎么样？',
  '大盘怎么样？',
  '主力在买什么？',
  '我的持仓怎么样？',
  '半导体板块怎么样',
  '创新药板块分析',
  '今日总结',
]

function scrollToBottom() {
  nextTick(() => {
    if (userScrolledUp.value) return
    scrollContainerRef.value?.scrollTo({
      top: scrollContainerRef.value.scrollHeight,
      behavior: 'smooth',
    })
  })
}

function jumpToLatest() {
  userScrolledUp.value = false
  nextTick(() => {
    scrollContainerRef.value?.scrollTo({
      top: scrollContainerRef.value.scrollHeight,
      behavior: 'smooth',
    })
  })
}

function onScroll(e: Event) {
  const target = e.target as HTMLElement
  if (!target) return
  const distFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight
  userScrolledUp.value = distFromBottom > 100
}

function renderMarkdown(text: string): string {
  const html = marked.parse(text) as string
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } })
}

function stopWorkingTimer() {
  if (nowTimer != null) {
    window.clearInterval(nowTimer)
    nowTimer = null
  }
  turnStart.value = 0
}

function stopGeneration() {
  const assistantIdx = activeAssistantIdx
  activeRequestId += 1
  routeAbortController?.abort()
  routeAbortController = null

  if (stream.value) {
    stream.value.close()
    stream.value = null
  }
  connectionState.value = 'idle'
  loading.value = false
  activeAssistantIdx = null
  stopWorkingTimer()

  if (assistantIdx != null) {
    const assistant = messages.value[assistantIdx]
    if (assistant?.role === 'assistant' && assistant.streaming) {
      assistant.streaming = false
      if (!assistant.content) {
        assistant.content = '（已停止）'
      }
    }
  }
}

async function send(message: string) {
  const text = message.trim()
  if (!text || loading.value) return
  const requestId = ++activeRequestId

  // 清除上次的错误状态
  lastFailedMessage.value = ''

  routeAbortController?.abort()
  routeAbortController = null
  if (stream.value) {
    stream.value.close()
    stream.value = null
  }
  connectionState.value = 'idle'

  // 显示用户消息
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  currentVerb.value = randomVerb()
  turnStart.value = Date.now()
  nowTimer ??= window.setInterval(() => {
    nowTick.value = Date.now()
  }, 100)

  // 创建 assistant 占位
  const assistantIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  activeAssistantIdx = assistantIdx
  scrollToBottom()

  // 先尝试工作流路由（快速路径）
  const routeController = new AbortController()
  routeAbortController = routeController
  try {
    const res = await agentRoute(text, routeController.signal)
    if (requestId !== activeRequestId) return
    if (res.matched && res.reply) {
      messages.value[assistantIdx] = {
        role: 'assistant',
        content: res.reply,
        workflowId: res.workflow_id,
        steps: res.steps?.filter((s) => s.success).map((s) => s.name),
        stepsRaw: res.steps?.map((s) => ({ name: s.name, success: s.success })),
        streaming: false,
      }
      loading.value = false
      connectionState.value = 'idle'
      activeAssistantIdx = null
      stopWorkingTimer()
      scrollToBottom()
      return
    }
  } catch {
    if (requestId !== activeRequestId) return
    // 路由失败，继续走 LLM 对话
  } finally {
    if (routeAbortController === routeController) {
      routeAbortController = null
    }
  }

  if (requestId !== activeRequestId) return

  // Fallback: WebSocket 流式对话
  // 构造 history（最近 10 轮，排除当前用户/助手占位）
  const history = messages.value
    .slice(Math.max(0, messages.value.length - 22), -2)
    .map((m) => ({ role: m.role, content: m.content }))

  let currentText = ''
  stream.value = agentStream(
    (chunk: string) => {
      if (requestId !== activeRequestId) return
      currentText += chunk
      messages.value[assistantIdx].content = currentText
      scrollToBottom()
    },
    (toolsUsed: string[], _rounds: number) => {
      if (requestId !== activeRequestId) return
      messages.value[assistantIdx].toolsUsed = toolsUsed
      messages.value[assistantIdx].streaming = false
      loading.value = false
      activeAssistantIdx = null
      stopWorkingTimer()
      scrollToBottom()
    },
    () => {
      if (requestId !== activeRequestId) return
      // thinking — 清空占位文案，进入"打字中"状态
      messages.value[assistantIdx].content = ''
    },
    (msg: string) => {
      if (requestId !== activeRequestId) return
      messages.value[assistantIdx].content = msg
      messages.value[assistantIdx].error = true
      messages.value[assistantIdx].streaming = false
      loading.value = false
      connectionState.value = 'disconnected'
      lastFailedMessage.value = text
      activeAssistantIdx = null
      stopWorkingTimer()
      scrollToBottom()
    },
    (state) => {
      if (requestId === activeRequestId) connectionState.value = state
    },
  )

  stream.value.send(text, history)
}

function handleSend() {
  send(input.value)
}

function handleQuick(q: string) {
  send(q)
}

function retry() {
  if (!lastFailedMessage.value) return
  // 移除报错的 assistant 消息（最后一条）
  const last = messages.value[messages.value.length - 1]
  if (last && last.role === 'assistant' && last.error) {
    messages.value.pop()
  }
  send(lastFailedMessage.value)
}

function restoreConversation() {
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
    // Ignore invalid or unavailable session storage and start a fresh view.
  }
}

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
      // Storage may be unavailable or full; chat remains usable in memory.
    }
  },
  { deep: true },
)

watch(input, (value) => {
  try {
    if (value) window.sessionStorage.setItem(CHAT_DRAFT_KEY, value)
    else window.sessionStorage.removeItem(CHAT_DRAFT_KEY)
  } catch {
    // Storage may be unavailable; the live draft remains intact.
  }
})

onMounted(() => {
  restoreConversation()
  if (messages.value.length === 0) {
    messages.value.push({
      role: 'assistant',
      content:
        '你好，我是妈妈的行情助手。\n\n我可以帮你：\n- 看行情 — "今天怎么样"\n- 分析股票 — "分析比亚迪"\n- 看板块 — "半导体板块怎么样"\n- 看资金 — "主力在买什么"\n- 看持仓 — "我的持仓怎么样"\n- 写报告 — "今日总结"\n\n试试下面的快捷按钮，或直接问我。',
    })
  }
  // dashboard 跳转带 q 参数 → 自动发送
  const q = route.query.q
  if (typeof q === 'string' && q.trim()) {
    const { q: _q, ...remainingQuery } = route.query
    void router.replace({ query: remainingQuery })
    nextTick(() => send(q))
  }
})

onUnmounted(() => {
  activeRequestId += 1
  routeAbortController?.abort()
  routeAbortController = null
  if (stream.value) {
    stream.value.close()
    stream.value = null
  }
  stopWorkingTimer()
})

/** slash 命令处理（来自 InputBar 的 / 命令） */
const SLASH_ALIASES: Record<string, string> = {
  morning: '今天怎么样',
  market: '大盘怎么样',
  portfolio: '我的持仓怎么样',
  flows: '主力在买什么',
  signals: '最近触发了哪些信号',
  earnings: '最近有哪些业绩披露',
}
function handleSlash(raw: string) {
  const body = raw.replace(/^\//, '').trim()
  const [name, ...rest] = body.split(/\s+/)
  const lower = name.toLowerCase()
  if (lower === 'clear' || lower === 'new') {
    messages.value = []
    return
  }
  if (lower === 'watch' && rest.length) {
    void send(rest.join(' '))
    return
  }
  if (lower === 'theme' && rest.length) {
    // 简单透传：toggle 主题留给 App.vue 的设置入口，这里只给提示
    messages.value.push({
      role: 'assistant',
      content: '主题切换请在 设置 里操作（深色/浅色）。',
    })
    return
  }
  const alias = SLASH_ALIASES[lower]
  if (alias) {
    void send(alias)
    return
  }
  // 未识别：当作普通问题发给 agent
  void send(raw)
}
</script>

<template>
  <div class="flex h-[calc(100dvh-var(--mobile-nav-height))] flex-col bg-background md:h-dvh">
    <!-- 顶栏：Kimi 风状态栏 -->
    <StatusBar :connection="connectionLevel" brand="mommy-chaogu" />

    <!-- 对话消息区 -->
    <div class="relative min-h-0 flex-1">
      <div
        ref="scrollContainerRef"
        class="h-full overflow-y-auto"
        :aria-busy="loading"
        @scroll="onScroll"
      >
        <div class="mx-auto w-full max-w-3xl space-y-3.5 px-3.5 py-4">
          <template v-for="(msg, i) in messages" :key="i">
            <!-- 用户消息 -->
            <MessageBubble v-if="msg.role === 'user'" role="user" :content="msg.content" />

            <!-- 助手消息 -->
            <div v-else class="space-y-2">
              <!-- 工作流匹配卡（命中工作流时，step 来自后端 RouteStep） -->
              <WorkflowCard
                v-if="msg.workflowId && msg.stepsRaw"
                :title="msg.workflowId"
                :steps="toWorkflowSteps(msg.stepsRaw)"
              />

              <!-- 工具调用行（done.tools_used 是事后列表；后端补 tool 事件前用 done 态展示） -->
              <ToolRow
                v-for="t in msg.toolsUsed ?? []"
                :key="t"
                :tool="t"
                status="done"
              />

              <!-- 消息正文 -->
              <MessageBubble
                role="assistant"
                :html="msg.error ? undefined : renderMarkdown(msg.content)"
                :content="msg.error ? msg.content : undefined"
                :streaming="msg.streaming && !msg.content"
              />

              <!-- 单轮脚注 -->
              <div
                v-if="msg.toolsUsed && msg.toolsUsed.length"
                class="pl-4 font-mono text-[11px] text-muted-foreground/70"
              >
                {{ msg.toolsUsed.map(toolDisplayName).join(' · ') }}
              </div>
            </div>
          </template>
        </div>
      </div>

      <Button
        v-if="userScrolledUp"
        variant="secondary"
        size="sm"
        class="absolute bottom-4 left-1/2 -translate-x-1/2 gap-1 rounded-full shadow-lg"
        aria-label="跳到最新消息"
        @click="jumpToLatest"
      >
        <ArrowDown class="size-4" aria-hidden="true" />
        最新
      </Button>
    </div>

    <!-- 工作中指示 -->
    <WorkingIndicator
      v-if="loading && !lastFailedMessage"
      :verb="currentVerb"
      :elapsed-ms="turnElapsedMs"
    />

    <!-- 快捷 chips -->
    <div
      class="flex gap-2 overflow-x-auto px-3.5 py-1.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      <button
        v-for="q in quickQuestions"
        :key="q"
        :disabled="loading"
        class="min-h-9 shrink-0 rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
        @click="handleQuick(q)"
      >
        {{ q }}
      </button>
    </div>

    <!-- 停止/重试 操作条 -->
    <div
      v-if="(loading && !lastFailedMessage) || lastFailedMessage"
      class="flex justify-center px-3.5 pt-1.5"
    >
      <Button
        v-if="loading && !lastFailedMessage"
        variant="destructive"
        size="sm"
        class="gap-1.5 font-mono"
        aria-label="停止生成"
        @click="stopGeneration"
      >
        ■ 停止
      </Button>
      <Button
        v-else-if="lastFailedMessage"
        variant="outline"
        size="sm"
        class="gap-1.5 font-mono"
        aria-label="重试"
        @click="retry"
      >
        ↻ 重试
      </Button>
    </div>

    <!-- 底部输入栏 -->
    <InputBar
      v-model="input"
      :disabled="loading && !lastFailedMessage"
      :busy="!!(loading && !lastFailedMessage)"
      :placeholder="loading ? '处理中…' : '问点什么…  / 看命令'"
      @send="(t) => send(t)"
      @slash="(c) => handleSlash(c)"
    />
  </div>
</template>

<style>
/* v-html 内容不受 scoped 样式影响，用全局样式 */
.markdown-body > *:first-child {
  margin-top: 0;
}
.markdown-body > *:last-child {
  margin-bottom: 0;
}
.markdown-body p {
  margin: 0.5em 0;
}
.markdown-body ul,
.markdown-body ol {
  margin: 0.5em 0;
  padding-left: 1.5em;
}
.markdown-body li {
  margin: 0.25em 0;
}
.markdown-body code {
  background: hsl(var(--muted));
  border-radius: 0.25rem;
  padding: 0.1em 0.3em;
  font-size: 0.875em;
  font-family: ui-monospace, monospace;
}
.markdown-body pre {
  background: hsl(var(--muted));
  border-radius: 0.5rem;
  padding: 0.75em 1em;
  overflow-x: auto;
  margin: 0.5em 0;
}
.markdown-body pre code {
  background: none;
  padding: 0;
}
.markdown-body blockquote {
  border-left: 3px solid hsl(var(--border));
  margin: 0.5em 0;
  padding: 0.25em 0 0.25em 1em;
  color: hsl(var(--muted-foreground));
}
.markdown-body a {
  color: hsl(var(--primary));
  text-decoration: underline;
}
.markdown-body strong {
  font-weight: 600;
}
.markdown-body h1,
.markdown-body h2,
.markdown-body h3 {
  font-weight: 600;
  margin: 0.75em 0 0.25em;
}
.markdown-body h1 {
  font-size: 1.25em;
}
.markdown-body h2 {
  font-size: 1.125em;
}
.markdown-body h3 {
  font-size: 1em;
}
.markdown-body table {
  border-collapse: collapse;
  margin: 0.5em 0;
  font-size: 0.875em;
}
.markdown-body th,
.markdown-body td {
  border: 1px solid hsl(var(--border));
  padding: 0.25em 0.5em;
}
</style>
