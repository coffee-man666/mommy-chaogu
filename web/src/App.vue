<script setup lang="ts">
import { RouterView, RouterLink } from 'vue-router'
</script>

<template>
  <div class="app">
    <RouterView />
    <nav class="tab-bar">
      <RouterLink to="/" class="tab-item">
        <span class="tab-icon">📊</span>
        <span>行情</span>
      </RouterLink>
      <RouterLink to="/portfolio" class="tab-item">
        <span class="tab-icon">💰</span>
        <span>持仓</span>
      </RouterLink>
      <RouterLink to="/signals" class="tab-item">
        <span class="tab-icon">🔔</span>
        <span>信号</span>
      </RouterLink>
      <RouterLink to="/settings" class="tab-item">
        <span class="tab-icon">⚙️</span>
        <span>设置</span>
      </RouterLink>
    </nav>
  </div>
</template>

<style>
/* 全局重置 */
html, body, #app, .app {
  margin: 0;
  padding: 0;
  width: 100%;
  min-height: 100vh;
  background: var(--color-bg);
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Helvetica, "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 14px;
  color: #333;
  line-height: 1.5;
}

button {
  font-family: inherit;
  font-size: inherit;
}

.app {
  padding-bottom: 60px;
}

.tab-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 56px;
  background: white;
  border-top: 1px solid var(--color-border);
  display: flex;
  z-index: 100;
}

.tab-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #999;
  gap: 2px;
}

.tab-item.router-link-active {
  color: var(--color-primary);
  font-weight: 600;
}

.tab-icon {
  font-size: 20px;
}
</style>
