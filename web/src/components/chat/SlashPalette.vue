<script setup lang="ts">
// Slash 命令浮层（移动端触屏：候选列表 + 说明，单选高亮，点选确认）。
// 移植自 TUI SLASH_COMMANDS（裁剪到 web 有意义的子集）。
import { computed } from 'vue'

export interface SlashCommand {
  name: string
  desc: string
  /** 有参数（如 /watch <code>）；用于 placeholder 提示 */
  hasArgs?: boolean
}

const props = defineProps<{
  /** 当前输入的 / 前缀文本（用于过滤） */
  query: string
  /** 当前高亮索引 */
  activeIndex: number
}>()

const emit = defineEmits<{
  select: [cmd: SlashCommand]
}>()

const COMMANDS: SlashCommand[] = [
  { name: 'help', desc: '显示帮助' },
  { name: 'clear', desc: '清空对话' },
  { name: 'dashboard', desc: '切到看板' },
  { name: 'theme', desc: '切换主题' },
  { name: 'morning', desc: '今日行情概览' },
  { name: 'market', desc: '大盘行情' },
  { name: 'portfolio', desc: '持仓点评' },
  { name: 'flows', desc: '资金流检查' },
  { name: 'signals', desc: '最近信号' },
  { name: 'watch', desc: '打开个股', hasArgs: true },
  { name: 'theme', desc: '主题分析', hasArgs: true },
  { name: 'earnings', desc: '业绩查询', hasArgs: true },
  { name: 'memory', desc: '记忆系统' },
]

const filtered = computed(() => {
  const q = props.query.replace(/^\//, '').toLowerCase()
  if (!q) return COMMANDS
  return COMMANDS.filter((c) => c.name.toLowerCase().includes(q))
})

defineExpose({ filtered })
</script>

<template>
  <div
    class="absolute bottom-full left-2 right-2 mb-1 max-h-64 overflow-y-auto rounded-lg border border-border bg-card p-1 shadow-lg"
  >
    <button
      v-for="(c, i) in filtered"
      :key="c.name"
      class="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-sm"
      :class="i === props.activeIndex ? 'bg-primary/15 text-foreground' : 'text-muted-foreground'"
      @click="emit('select', c)"
    >
      <span class="font-mono text-primary">/{{ c.name }}</span>
      <span class="text-xs text-muted-foreground">{{ c.desc }}</span>
    </button>
    <div v-if="filtered.length === 0" class="px-2.5 py-2 text-xs text-muted-foreground">
      无匹配命令
    </div>
  </div>
</template>
