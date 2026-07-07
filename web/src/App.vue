<script setup lang="ts">
import { RouterView, RouterLink } from 'vue-router'
</script>

<template>
  <div class="app">
    <!-- 桌面端侧边导航 -->
    <nav class="sidebar">
      <div class="sidebar-logo">📊 投研</div>
      <RouterLink to="/dashboard" class="sidebar-item">
        <span class="sidebar-icon">🏠</span>
        <span>仪表盘</span>
      </RouterLink>
      <RouterLink to="/market" class="sidebar-item">
        <span class="sidebar-icon">📈</span>
        <span>行情</span>
      </RouterLink>
      <RouterLink to="/portfolio" class="sidebar-item">
        <span class="sidebar-icon">💰</span>
        <span>持仓</span>
      </RouterLink>
      <RouterLink to="/agent" class="sidebar-item">
        <span class="sidebar-icon">💬</span>
        <span>问</span>
      </RouterLink>
      <RouterLink to="/signals" class="sidebar-item">
        <span class="sidebar-icon">🔔</span>
        <span>信号</span>
      </RouterLink>
      <RouterLink to="/settings" class="sidebar-item">
        <span class="sidebar-icon">⚙️</span>
        <span>设置</span>
      </RouterLink>
    </nav>

    <!-- 主内容区 -->
    <main class="main-content">
      <RouterView />
    </main>

    <!-- 移动端底部 tab -->
    <nav class="tab-bar">
      <RouterLink to="/market" class="tab-item">
        <span class="tab-icon">📈</span>
        <span>行情</span>
      </RouterLink>
      <RouterLink to="/portfolio" class="tab-item">
        <span class="tab-icon">💰</span>
        <span>持仓</span>
      </RouterLink>
      <RouterLink to="/agent" class="tab-item">
        <span class="tab-icon">💬</span>
        <span>问</span>
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

/* ========== 桌面端布局（≥768px） ========== */

.app {
  display: flex;
  padding-bottom: 0;
}

.sidebar {
  display: none;
  width: 64px;
  min-height: 100vh;
  background: var(--color-surface, #fff);
  border-right: 1px solid var(--color-border, #eee);
  flex-direction: column;
  align-items: center;
  padding: 12px 0;
  gap: 4px;
  position: sticky;
  top: 0;
  z-index: 100;
}

.sidebar-logo {
  font-size: 24px;
  margin-bottom: 16px;
  padding: 8px 0;
}

.sidebar-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 10px;
  font-size: 11px;
  color: #999;
  text-decoration: none;
  gap: 3px;
  transition: background 0.15s;
}

.sidebar-item:hover {
  background: var(--color-bg, #f5f5f5);
}

.sidebar-item.router-link-active {
  color: var(--color-primary);
  background: var(--color-primary) 10;
  font-weight: 600;
}

.sidebar-icon {
  font-size: 20px;
}

.main-content {
  flex: 1;
  min-width: 0;
  padding-bottom: 0;
}

.tab-bar {
  display: flex;
}

@media (min-width: 768px) {
  .sidebar {
    display: flex;
  }

  .main-content {
    padding-bottom: 0;
  }

  .tab-bar {
    display: none;
  }
}

/* ========== 移动端布局（<768px） ========== */

@media (max-width: 767px) {
  .app {
    flex-direction: column;
    padding-bottom: 60px;
  }

  .main-content {
    padding-bottom: 60px;
  }
}

.tab-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 56px;
  background: white;
  border-top: 1px solid var(--color-border, #eee);
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
  text-decoration: none;
}

.tab-item.router-link-active {
  color: var(--color-primary);
  font-weight: 600;
}

.tab-icon {
  font-size: 20px;
}
</style>
