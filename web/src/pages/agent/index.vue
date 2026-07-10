<script setup lang="ts">
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { agentStream, agentRoute } from '@/api/agent'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import { Bot, Send, User, Wrench, CheckCircle2, Zap } from 'lucide-vue-next'

interface Message {
  role: 'user' | 'assistant'
  content: string
  toolsUsed?: string[]
  steps?: string[]
  workflowId?: string
  streaming?: boolean
  error?: boolean
}

const route = useRoute()
const messages = ref<Message[]>([])
const input = ref('')
const loading = ref(false)
const bottomRef = ref<HTMLElement>()
const stream = ref<ReturnType<typeof agentStream> | null>(null)

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
    bottomRef.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  })
}

async function send(message: string) {
  const text = message.trim()
  if (!text || loading.value) return

  // 显示用户消息
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true

  // 创建 assistant 占位
  const assistantIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '', streaming: true })
  scrollToBottom()

  // 先尝试工作流路由（快速路径）
  try {
    const res = await agentRoute(text)
    if (res.matched && res.reply) {
      messages.value[assistantIdx] = {
        role: 'assistant',
        content: res.reply,
        workflowId: res.workflow_id,
        steps: res.steps?.filter((s) => s.success).map((s) => s.name),
        streaming: false,
      }
      loading.value = false
      scrollToBottom()
      return
    }
  } catch {
    // 路由失败，继续走 LLM 对话
  }

  // Fallback: WebSocket 流式对话
  // 构造 history（最近 10 轮，排除当前用户/助手占位）
  const history = messages.value
    .slice(Math.max(0, messages.value.length - 22), -2)
    .map((m) => ({ role: m.role, content: m.content }))

  if (stream.value) {
    stream.value.close()
  }

  let currentText = ''
  stream.value = agentStream(
    (chunk: string) => {
      currentText += chunk
      messages.value[assistantIdx].content = currentText
      scrollToBottom()
    },
    (toolsUsed: string[], _rounds: number) => {
      messages.value[assistantIdx].toolsUsed = toolsUsed
      messages.value[assistantIdx].streaming = false
      loading.value = false
      scrollToBottom()
    },
    () => {
      // thinking — 清空占位文案，进入"打字中"状态
      messages.value[assistantIdx].content = ''
    },
    (msg: string) => {
      messages.value[assistantIdx].content = msg
      messages.value[assistantIdx].error = true
      messages.value[assistantIdx].streaming = false
      loading.value = false
      scrollToBottom()
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

onMounted(() => {
  // 欢迎消息
  messages.value.push({
    role: 'assistant',
    content:
      '你好！我是妈妈的行情助手 📋\n\n我可以帮你：\n· 看行情 — "今天怎么样"\n· 分析股票 — "分析比亚迪"\n· 看板块 — "半导体板块怎么样"\n· 看资金 — "主力在买什么"\n· 看持仓 — "我的持仓怎么样"\n· 写报告 — "今日总结"\n\n试试下面的快捷按钮，或者直接问我！',
  })
  // dashboard 跳转带 q 参数 → 自动发送
  const q = route.query.q
  if (typeof q === 'string' && q.trim()) {
    nextTick(() => send(q))
  }
})

onUnmounted(() => {
  if (stream.value) {
    stream.value.close()
  }
})
</script>

<template>
  <div class="flex h-[calc(100dvh-4rem)] flex-col bg-muted/30 md:h-dvh">
    <!-- 顶栏 -->
    <header
      class="flex shrink-0 items-center gap-2 border-b bg-card px-4 py-3"
    >
      <div
        class="flex size-8 items-center justify-center rounded-full bg-primary/10 text-primary"
      >
        <Bot class="size-5" />
      </div>
      <h1 class="text-base font-semibold tracking-tight">AI 对话</h1>
      <Badge
        v-if="loading"
        variant="secondary"
        class="gap-1"
      >
        <span class="size-1.5 animate-pulse rounded-full bg-primary" />
        思考中
      </Badge>
    </header>

    <!-- 对话消息区 -->
    <ScrollArea class="min-h-0 flex-1">
      <div class="mx-auto w-full max-w-3xl space-y-4 px-4 py-6">
        <div
          v-for="(msg, i) in messages"
          :key="i"
          :class="
            cn(
              'flex gap-3',
              msg.role === 'user' ? 'flex-row-reverse' : 'flex-row',
            )
          "
        >
          <!-- 头像 -->
          <div
            :class="
              cn(
                'flex size-8 shrink-0 items-center justify-center rounded-full',
                msg.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border text-muted-foreground',
              )
            "
          >
            <User v-if="msg.role === 'user'" class="size-4" />
            <Bot v-else class="size-4" />
          </div>

          <!-- 气泡 + 元信息 -->
          <div
            :class="
              cn(
                'flex min-w-0 max-w-[80%] flex-col gap-1',
                msg.role === 'user' ? 'items-end' : 'items-start',
              )
            "
          >
            <!-- 工作流来源标签 -->
            <Badge
              v-if="msg.workflowId"
              variant="outline"
              class="gap-1 text-up"
            >
              <Zap class="size-3" />
              {{ msg.workflowId }}
            </Badge>

            <!-- 气泡 -->
            <div
              :class="
                cn(
                  'whitespace-pre-wrap break-words px-4 py-2.5 text-sm leading-relaxed shadow-sm',
                  msg.role === 'user'
                    ? 'rounded-2xl rounded-tr-sm bg-primary text-primary-foreground'
                    : msg.error
                      ? 'rounded-2xl rounded-tl-sm border-destructive/30 bg-destructive/5 text-destructive'
                      : 'rounded-2xl rounded-tl-sm border bg-card text-card-foreground',
                )
              "
            >
              <!-- 打字中指示器 -->
              <span
                v-if="msg.streaming && !msg.content"
                class="inline-flex items-center gap-1 py-0.5"
              >
                <span
                  class="size-2 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:-0.3s]"
                />
                <span
                  class="size-2 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:-0.15s]"
                />
                <span class="size-2 animate-bounce rounded-full bg-muted-foreground/50" />
              </span>
              <template v-else>{{ msg.content }}</template>
            </div>

            <!-- 工作流步骤标签 -->
            <div
              v-if="msg.steps && msg.steps.length > 0"
              class="flex flex-wrap gap-1"
            >
              <Badge
                v-for="s in msg.steps"
                :key="s"
                variant="outline"
                class="gap-1 text-up"
              >
                <CheckCircle2 class="size-3" />
                {{ s }}
              </Badge>
            </div>

            <!-- 工具调用折叠展示 -->
            <details
              v-if="msg.toolsUsed && msg.toolsUsed.length > 0"
              class="group"
            >
              <summary
                class="inline-flex cursor-pointer list-none items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                <Wrench class="size-3" />
                <span>
                  工具调用 ({{ msg.toolsUsed.length }})
                </span>
                <span class="text-muted-foreground/60 group-open:rotate-180 transition-transform">▾</span>
              </summary>
              <div class="mt-1.5 flex flex-wrap gap-1">
                <Badge
                  v-for="t in msg.toolsUsed"
                  :key="t"
                  variant="secondary"
                  class="font-mono text-xs"
                >
                  {{ t }}
                </Badge>
              </div>
            </details>
          </div>
        </div>

        <!-- 滚动锚点 -->
        <div ref="bottomRef" />
      </div>
    </ScrollArea>

    <!-- 底部：快捷问题 + 输入区 -->
    <div class="shrink-0 border-t bg-card">
      <div class="mx-auto w-full max-w-3xl">
        <!-- 快捷问题 -->
        <div class="flex gap-2 overflow-x-auto px-4 py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <Button
            v-for="q in quickQuestions"
            :key="q"
            variant="outline"
            size="sm"
            class="shrink-0 rounded-full"
            :disabled="loading"
            @click="handleQuick(q)"
          >
            {{ q }}
          </Button>
        </div>

        <Separator />

        <!-- 输入区 -->
        <div class="flex items-center gap-2 px-4 py-3">
          <Input
            v-model="input"
            placeholder="问点什么..."
            :disabled="loading"
            class="flex-1"
            @keydown.enter="handleSend"
          />
          <Button
            :disabled="loading || !input.trim()"
            size="icon"
            @click="handleSend"
          >
            <Send class="size-4" />
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
