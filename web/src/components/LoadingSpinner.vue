<script setup lang="ts">
const props = withDefaults(defineProps<{
  text?: string
}>(), {
  text: '加载中...',
})
</script>

<template>
  <div class="loading-spinner">
    <div class="spinner" />
    <span>{{ props.text }}</span>
  </div>
</template>

<style scoped>
.loading-spinner {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  color: #999;
  gap: 12px;
  font-size: 14px;
}
.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #eee;
  border-top-color: var(--color-primary, #c83e3e);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
