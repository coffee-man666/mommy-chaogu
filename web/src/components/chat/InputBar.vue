<script setup lang="ts">
// 底部常驻输入栏（Kimi 灵魂）：/ 按钮 + 自适应 textarea + 发送 ↑。
// - 输入 / 触发 SlashPalette 浮层
// - 发送态：disabled + 文案改"发送中"
import { ref, computed, watch, nextTick } from 'vue'
import SlashPalette, { type SlashCommand } from './SlashPalette.vue'

const props = defineProps<{
  disabled?: boolean
  placeholder?: string
  busy?: boolean
}>()

const model = defineModel<string>({ default: '' })
const emit = defineEmits<{
  send: [text: string]
  slash: [cmd: string]
}>()

const ta = ref<HTMLTextAreaElement | null>(null)
const slashOpen = ref(false)
const slashActive = ref(0)
const palette = ref<InstanceType<typeof SlashPalette> | null>(null)

const isSlash = computed(() => model.value.startsWith('/'))
const filteredCount = computed(() => palette.value?.filtered.length ?? 0)

watch(model, (v) => {
  if (v.startsWith('/')) {
    slashOpen.value = true
    slashActive.value = 0
  } else {
    slashOpen.value = false
  }
})

watch(model, async () => {
  await nextTick()
  if (ta.value) {
    ta.value.style.height = 'auto'
    ta.value.style.height = Math.min(96, ta.value.scrollHeight) + 'px'
  }
})

function doSend() {
  const text = model.value.trim()
  if (!text || props.disabled) return
  if (isSlash.value) {
    emit('slash', text)
    model.value = ''
    slashOpen.value = false
    return
  }
  emit('send', text)
  model.value = ''
}

function onKeydown(e: KeyboardEvent) {
  if (slashOpen.value && filteredCount.value > 0) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      slashActive.value = (slashActive.value + 1) % filteredCount.value
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      slashActive.value = (slashActive.value - 1 + filteredCount.value) % filteredCount.value
      return
    }
  }
  // 移动端通常没有 Enter 发送（要换行），这里用 Cmd/Ctrl+Enter 或 发送按钮
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault()
    doSend()
  }
}

function onSelectCmd(c: SlashCommand) {
  model.value = `/${c.name}${c.hasArgs ? ' ' : ''}`
  slashOpen.value = false
  ta.value?.focus()
}

defineExpose({ focus: () => ta.value?.focus() })
</script>

<template>
  <div class="relative border-t border-border bg-background">
    <!-- Slash 命令浮层 -->
    <SlashPalette
      v-if="slashOpen"
      ref="palette"
      :query="model"
      :active-index="slashActive"
      @select="onSelectCmd"
    />

    <div
      class="flex items-end gap-2 px-3.5 pb-[calc(0.5rem+env(safe-area-inset-bottom))] pt-2"
    >
      <button
        class="h-[34px] w-[34px] shrink-0 rounded-lg border border-border font-mono text-base text-muted-foreground"
        :disabled="props.disabled"
        title="命令"
        @click="
          () => {
            model = model.startsWith('/') ? model : '/'
            ta?.focus()
          }
        "
      >
        /
      </button>
      <textarea
        ref="ta"
        v-model="model"
        :rows="1"
        :placeholder="props.placeholder ?? '问点什么…  / 看命令'"
        :disabled="props.disabled"
        class="max-h-24 min-h-[34px] flex-1 resize-none rounded-[10px] border border-border bg-card px-2.5 py-2 text-[15px] text-foreground outline-none placeholder:text-muted-foreground/70 focus:border-primary disabled:opacity-60"
        @keydown="onKeydown"
      />
      <button
        class="h-[34px] w-[34px] shrink-0 rounded-lg bg-primary font-mono text-lg text-primary-foreground disabled:opacity-50"
        :disabled="props.disabled || props.busy || !model.trim()"
        @click="doSend"
      >
        ↑
      </button>
    </div>
  </div>
</template>
