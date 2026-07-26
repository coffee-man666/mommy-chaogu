<script setup lang="ts">
// Kimi 风消息气泡：
// - 用户：roleUser 金黄 + • bullet（kimi -p 实测确认 assistant 用 • bullet；用户沿用项目 TUI 的金黄色）
// - 助手：text 色，无气泡背景，像终端输出；• bullet（primary 蓝）
// 助手内容可选 markdown（外部已 sanitize 成 html，这里只 v-html）。
import { computed } from 'vue'

const props = defineProps<{
  role: 'user' | 'assistant'
  /** 助手消息可选：已 sanitize 的 html（外部 DOMPurify 处理） */
  html?: string
  /** 纯文本（用户消息、或助手 fallback） */
  content?: string
  streaming?: boolean
}>()

const isUser = computed(() => props.role === 'user')
</script>

<template>
  <div class="flex items-start gap-2" :class="isUser ? 'text-[hsl(43_100_72%)]' : ''">
    <!-- 项目 TUI 用实心圆作为 bullet；kimi -p 实测 assistant 也用 • (U+2022) -->
    <span class="mt-px select-none font-bold" :class="isUser ? 'text-[hsl(43_100_72%)]' : 'text-primary'">•</span>
    <div class="min-w-0 flex-1">
      <div v-if="isUser" class="text-[hsl(43_100_72%)]">{{ props.content }}</div>
      <div v-else>
        <div v-if="props.html" class="markdown-body text-foreground" v-html="props.html" />
        <div v-else-if="props.streaming" class="text-muted-foreground">
          <span class="inline-flex gap-0.5">
            <span class="animate-bounce [animation-delay:-0.3s]">·</span>
            <span class="animate-bounce [animation-delay:-0.15s]">·</span>
            <span class="animate-bounce">·</span>
          </span>
        </div>
        <div v-else-if="props.content" class="text-foreground">{{ props.content }}</div>
      </div>
    </div>
  </div>
</template>
