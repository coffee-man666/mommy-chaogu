<script setup lang="ts">
withDefaults(defineProps<{
  icon?: string
  title?: string
  hint?: string
}>(), {
  icon: '📭',
  title: '暂无数据',
  hint: '',
})
</script>

<template>
  <div class="empty-state">
    <span class="icon">{{ icon }}</span>
    <p class="title">{{ title }}</p>
    <p v-if="hint" class="hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  color: #999;
  gap: 8px;
}
.icon { font-size: 36px; }
.title { font-size: 15px; font-weight: 500; margin: 0; }
.hint { font-size: 13px; color: #bbb; margin: 0; }
</style>
