<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet } from '../../api/client'
import EmptyState from '../../components/EmptyState.vue'

interface Theme {
  id: string
  name: string
  description: string
  total_stocks: number
  subcategories: string[]
  source: string
}

const router = useRouter()
const themes = ref<Theme[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    const data = await apiGet<{ items: Theme[]; total: number }>('/api/themes')
    themes.value = data.items
  } catch {
    themes.value = []
  } finally {
    loading.value = false
  }
})

const themeIcons: Record<string, string> = {
  semiconductor: '🔧',
  innovative_drug: '💊',
  humanoid_robot: '🤖',
  materials: '🧱',
  earnings_watch: '📊',
}
</script>

<template>
  <div class="themes-page">
    <h2 class="page-title">主题观察</h2>
    <p class="page-desc">产业链全景 + 中报高增长观察</p>

    <EmptyState v-if="!loading && themes.length === 0" icon="📂" title="暂无主题数据" />

    <div class="theme-grid">
      <div
        v-for="t in themes"
        :key="t.id"
        class="theme-card"
        @click="router.push(`/themes/${t.id}`)"
      >
        <div class="theme-icon">{{ themeIcons[t.id] || '📈' }}</div>
        <div class="theme-info">
          <div class="theme-name">{{ t.name }}</div>
          <div class="theme-desc">{{ t.description }}</div>
          <div class="theme-meta">
            <span class="stock-count">{{ t.total_stocks }} 只</span>
            <span v-if="t.subcategories.length" class="sub-count">
              {{ t.subcategories.length }} 个子板块
            </span>
          </div>
        </div>
        <div class="theme-arrow">→</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.themes-page {
  padding: 16px;
  max-width: 900px;
  margin: 0 auto;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 4px;
}
.page-desc {
  font-size: 13px;
  color: #999;
  margin: 0 0 16px;
}

.theme-grid {
  display: grid;
  gap: 12px;
}

.theme-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #eee);
  border-radius: 12px;
  cursor: pointer;
  transition: box-shadow 0.15s, border-color 0.15s;
}
.theme-card:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  border-color: var(--color-primary, #c83e3e);
}

.theme-icon {
  font-size: 32px;
  flex-shrink: 0;
}

.theme-info {
  flex: 1;
  min-width: 0;
}
.theme-name {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}
.theme-desc {
  font-size: 13px;
  color: #888;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.theme-meta {
  display: flex;
  gap: 12px;
  margin-top: 6px;
  font-size: 12px;
}
.stock-count {
  color: var(--color-primary, #c83e3e);
  font-weight: 600;
}
.sub-count {
  color: #aaa;
}

.theme-arrow {
  font-size: 20px;
  color: #ccc;
  flex-shrink: 0;
}
</style>
