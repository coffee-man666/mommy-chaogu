<script setup lang="ts">
import { useRouter } from 'vue-router'

const props = defineProps<{
  code: string
  name?: string
}>()

const router = useRouter()

function goDetail() {
  if (props.code && /^\d{6}$/.test(props.code)) {
    router.push({ name: 'detail', params: { code: props.code } })
  }
}
</script>

<template>
  <span class="stock-tag" @click="goDetail">
    <span class="code">{{ code }}</span>
    <span v-if="name" class="name">{{ name }}</span>
  </span>
</template>

<style scoped>
.stock-tag {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.stock-tag:hover .name {
  text-decoration: underline;
}
.code {
  font-family: 'SF Mono', 'Menlo', monospace;
  font-size: 12px;
  color: #888;
}
.name {
  font-size: 14px;
  color: #333;
}
</style>
