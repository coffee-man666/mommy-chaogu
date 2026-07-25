<script setup lang="ts">
// 统一错误态：图标 + 中文说明 + 重试按钮
// 与空态（没有数据）严格区分——只在"加载失败"时使用
import { AlertCircle } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

withDefaults(
  defineProps<{
    /** 给用户看的中文说明，一般传 ApiError.friendly */
    message?: string
    /** 紧凑模式（嵌在卡片 / 区块内部时用） */
    compact?: boolean
  }>(),
  {
    message: '加载失败，请稍后再试',
    compact: false,
  },
)

const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div
    role="alert"
    class="flex flex-col items-center justify-center gap-3 text-center"
    :class="compact ? 'py-6' : 'py-12'"
  >
    <AlertCircle class="size-8 text-destructive/70" aria-hidden="true" />
    <p class="text-sm text-muted-foreground">{{ message }}</p>
    <Button variant="outline" size="sm" @click="emit('retry')">重试</Button>
  </div>
</template>
