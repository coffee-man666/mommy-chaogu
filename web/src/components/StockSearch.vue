<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { Search, LoaderCircle } from 'lucide-vue-next'
import { searchStocks } from '@/api/market'
import type { StockSearchResult } from '@/api/types'
import { cn } from '@/lib/utils'

export interface StockSearchProps {
  modelValue?: string
  placeholder?: string
  ariaLabel?: string
  class?: string
}

const props = withDefaults(defineProps<StockSearchProps>(), {
  modelValue: '',
  placeholder: '输入名称或代码',
  ariaLabel: '搜索股票',
  class: '',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  select: [stock: StockSearchResult]
}>()

const query = ref(props.modelValue)
const results = ref<StockSearchResult[]>([])
const loading = ref(false)
const open = ref(false)
const activeIndex = ref(-1)
let requestId = 0
let debounceTimer: number | null = null
let blurTimer: number | null = null

const listboxId = `stock-search-${Math.random().toString(36).slice(2)}`
const activeOptionId = computed(() =>
  activeIndex.value >= 0 ? `${listboxId}-${activeIndex.value}` : undefined,
)

const sourceLabels: Record<StockSearchResult['source'], string> = {
  watchlist: '自选',
  semicon: '产业链',
  cache: '历史',
}

async function runSearch(value: string) {
  const text = value.trim()
  if (!text) {
    results.value = []
    open.value = false
    return
  }
  const current = ++requestId
  loading.value = true
  try {
    const items = await searchStocks(text)
    if (current !== requestId) return
    results.value = items
    activeIndex.value = items.length ? 0 : -1
    open.value = true
  } catch {
    if (current !== requestId) return
    results.value = []
    activeIndex.value = -1
    open.value = true
  } finally {
    if (current === requestId) loading.value = false
  }
}

function onInput(event: Event) {
  const value = (event.target as HTMLInputElement).value
  query.value = value
  emit('update:modelValue', value)
  if (debounceTimer != null) window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(() => void runSearch(value), 180)
}

function choose(stock: StockSearchResult) {
  query.value = stock.code
  emit('update:modelValue', stock.code)
  emit('select', stock)
  open.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    open.value = true
    activeIndex.value = results.value.length
      ? (activeIndex.value + 1) % results.value.length
      : -1
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    open.value = true
    activeIndex.value = results.value.length
      ? (activeIndex.value - 1 + results.value.length) % results.value.length
      : -1
  } else if (event.key === 'Enter' && open.value && activeIndex.value >= 0) {
    event.preventDefault()
    const selected = results.value[activeIndex.value]
    if (selected) choose(selected)
  } else if (event.key === 'Escape') {
    open.value = false
  }
}

function onFocus() {
  if (blurTimer != null) window.clearTimeout(blurTimer)
  if (query.value.trim()) void runSearch(query.value)
}

function onBlur() {
  blurTimer = window.setTimeout(() => {
    open.value = false
  }, 120)
}

watch(
  () => props.modelValue,
  (value) => {
    if (value !== query.value) query.value = value
  },
)

onUnmounted(() => {
  if (debounceTimer != null) window.clearTimeout(debounceTimer)
  if (blurTimer != null) window.clearTimeout(blurTimer)
})
</script>

<template>
  <div :class="cn('relative', props.class)">
    <Search class="pointer-events-none absolute left-3 top-1/2 z-10 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
    <input
      :value="query"
      type="search"
      role="combobox"
      autocomplete="off"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      :aria-expanded="open"
      :aria-controls="listboxId"
      :aria-activedescendant="activeOptionId"
      class="flex h-10 w-full rounded-md border border-input bg-background py-2 pl-9 pr-9 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      @input="onInput"
      @keydown="onKeydown"
      @focus="onFocus"
      @blur="onBlur"
    />
    <LoaderCircle v-if="loading" class="absolute right-3 top-1/2 size-4 -translate-y-1/2 animate-spin text-muted-foreground" aria-hidden="true" />

    <ul
      v-if="open"
      :id="listboxId"
      role="listbox"
      class="absolute z-50 mt-1 max-h-72 w-full overflow-y-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-lg"
    >
      <li
        v-for="(stock, index) in results"
        :id="`${listboxId}-${index}`"
        :key="stock.code"
        role="option"
        :aria-selected="index === activeIndex"
      >
        <button
          type="button"
          class="flex min-h-11 w-full items-center gap-3 rounded-sm px-3 py-2 text-left text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          :class="index === activeIndex ? 'bg-accent' : ''"
          @mousedown.prevent="choose(stock)"
        >
          <span class="min-w-0 flex-1">
            <span class="block truncate font-medium">{{ stock.name || stock.code }}</span>
            <span class="font-mono text-xs text-muted-foreground">{{ stock.code }}</span>
          </span>
          <span class="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
            {{ sourceLabels[stock.source] }}
          </span>
        </button>
      </li>
      <li v-if="!loading && results.length === 0" class="px-3 py-4 text-center text-sm text-muted-foreground">
        没有匹配的股票，可直接输入 6 位代码
      </li>
    </ul>
  </div>
</template>
