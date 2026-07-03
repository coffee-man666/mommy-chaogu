<script setup lang="ts">
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { agentStream } from '../../api/agent'

interface Message {
  role: 'user' | 'assistant'
  content: string
  toolsUsed?: string[]
}

const messages = ref<Message[]>([])
const input = ref('')
const loading = ref(false)
const chatRef = ref<HTMLElement>()

const stream = ref<ReturnType<typeof agentStream> | null>(null)

// 快捷问题
const quickQuestions = [
  '我的持仓怎么样？',
  '今天大盘怎么样？',
  '创新药板块分析',
  '半导体板块分析',
  '有什么异动？',
]

function scrollToBottom() {
  nextTick(() => {
    if (chatRef.value) {
      chatRef.value.scrollTop = chatRef.value.scrollHeight
    }
  })
}

function send(message: string) {
  const text = message.trim()
  if (!text || loading.value) return

  // 显示用户消息
  messages.value.push({ role: 'user', content: text })
  input.value('')
  input.value = ''
  loading.value = true

  // 创建 assistant 占位
  const assistantIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '' })

  scrollToBottom()

  // 构造 history（最近 10 轮）
  const history = messages.value
    .slice(0, -2) // 排除当前这轮
    .map((m) => ({ role: m.role, content: m.content }))

  // 初始化 WS
  if (stream.value) {
    stream.value.close()
  }

  let currentText = ''
  stream.value = agentStream(
    // onChunk
    (chunk: string) => {
      currentText += chunk
      messages.value[assistantIdx].content = currentText
      scrollToBottom()
    },
    // onDone
    (toolsUsed: string[], _rounds: number) => {
      messages.value[assistantIdx].toolsUsed = toolsUsed
      loading.value = false
      scrollToBottom()
    },
    // onThinking
    () => {
      messages.value[assistantIdx].content = '思考中...'
      scrollToBottom()
    },
    // onError
    (msg: string) => {
      messages.value[assistantIdx].content = `❌ ${msg}`
      loading.value = false
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
    content: '你好！我是妈妈的行情助手。可以问我大盘行情、板块分析、持仓情况等。',
  })
})

onUnmounted(() => {
  if (stream.value) {
    stream.value.close()
  }
})
</script>

<template>
  <div class="agent-page">
    <!-- 对话区域 -->
    <div class="chat-area" ref="chatRef">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="msg-row"
        :class="msg.role === 'user' ? 'msg-user' : 'msg-bot'"
      >
        <div class="msg-bubble" :class="msg.role === 'user' ? 'bubble-user' : 'bubble-bot'">
          <span class="msg-text">{{ msg.content }}</span>
        </div>
        <div v-if="msg.toolsUsed && msg.toolsUsed.length > 0" class="msg-tools">
          🔧 {{ msg.toolsUsed.join(', ') }}
        </div>
      </div>
    </div>

    <!-- 快捷问题 -->
    <div class="quick-bar">
      <button
        v-for="q in quickQuestions"
        :key="q"
        class="quick-btn"
        :disabled="loading"
        @click="handleQuick(q)"
      >
        {{ q }}
      </button>
    </div>

    <!-- 输入区 -->
    <div class="input-bar">
      <input
        v-model="input"
        type="text"
        class="input-field"
        placeholder="问点什么..."
        :disabled="loading"
        @keydown.enter="handleSend"
      />
      <button class="send-btn" :disabled="loading || !input.trim()" @click="handleSend">
        {{ loading ? '...' : '发送' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.agent-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px);
  background: #f5f5f5;
}

.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.msg-row {
  display: flex;
  flex-direction: column;
  max-width: 85%;
}

.msg-user {
  align-self: flex-end;
  align-items: flex-end;
}

.msg-bot {
  align-self: flex-start;
  align-items: flex-start;
}

.msg-bubble {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
  white-space: pre-wrap;
}

.bubble-user {
  background: #1677ff;
  color: white;
  border-bottom-right-radius: 4px;
}

.bubble-bot {
  background: white;
  color: #333;
  border-bottom-left-radius: 4px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.msg-tools {
  font-size: 11px;
  color: #999;
  margin-top: 4px;
  padding: 0 4px;
}

.quick-bar {
  display: flex;
  gap: 6px;
  padding: 8px 12px;
  overflow-x: auto;
  background: white;
  border-top: 1px solid #eee;
  flex-shrink: 0;
}

.quick-btn {
  flex-shrink: 0;
  padding: 6px 12px;
  border: 1px solid #1677ff;
  background: white;
  color: #1677ff;
  border-radius: 16px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.quick-btn:active {
  background: #1677ff;
  color: white;
}

.quick-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-bar {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  background: white;
  border-top: 1px solid #eee;
  flex-shrink: 0;
}

.input-field {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
}

.input-field:focus {
  border-color: #1677ff;
}

.send-btn {
  padding: 8px 20px;
  background: #1677ff;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
}

.send-btn:disabled {
  background: #ccc;
  cursor: not-allowed;
}
</style>
