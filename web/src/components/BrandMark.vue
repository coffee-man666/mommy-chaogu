<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    alt?: string
    size?: 'sm' | 'md'
  }>(),
  {
    alt: '',
    size: 'md',
  },
)

const sizeClass = computed(() => (props.size === 'sm' ? 'size-9 rounded-xl' : 'size-11 rounded-2xl'))
</script>

<template>
  <span
    :class="[
      'relative inline-flex shrink-0 overflow-hidden border border-primary/20 bg-white shadow-sm',
      sizeClass,
    ]"
  >
    <img
      src="/mommy-chaogu-logo.jpg"
      :alt="alt"
      class="absolute left-1/2 top-[42%] w-[185%] max-w-none -translate-x-1/2 -translate-y-[38%]"
    />
  </span>
</template>
