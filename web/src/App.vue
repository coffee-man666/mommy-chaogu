<script setup lang="ts">
import { RouterView, RouterLink } from 'vue-router'
import { LayoutDashboard, TrendingUp, Microscope, Wallet, MessageSquare, Bell, Settings } from 'lucide-vue-next'
import { cn } from '@/lib/utils'
</script>

<template>
  <div class="flex min-h-screen bg-background text-foreground">
    <!-- 桌面端侧边导航 -->
    <nav class="hidden md:flex w-16 flex-col items-center gap-2 border-r bg-card py-4 sticky top-0 h-screen">
      <RouterLink to="/dashboard" title="仪表盘" aria-label="仪表盘" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <LayoutDashboard class="size-5" />
      </RouterLink>
      <RouterLink to="/market" title="行情" aria-label="行情" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <TrendingUp class="size-5" />
      </RouterLink>
      <RouterLink to="/themes" title="主题" aria-label="主题" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <Microscope class="size-5" />
      </RouterLink>
      <RouterLink to="/portfolio" title="持仓" aria-label="持仓" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <Wallet class="size-5" />
      </RouterLink>
      <RouterLink to="/agent" title="AI对话" aria-label="AI对话" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <MessageSquare class="size-5" />
      </RouterLink>
      <RouterLink to="/signals" title="信号" aria-label="信号" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <Bell class="size-5" />
      </RouterLink>
      <div class="flex-1" />
      <RouterLink to="/settings" title="设置" aria-label="设置" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <Settings class="size-5" />
      </RouterLink>
    </nav>

    <!-- 主内容区 -->
    <main class="flex-1 min-w-0 pb-16 md:pb-0">
      <RouterView />
    </main>

    <!-- 移动端底部 tab -->
    <nav class="fixed bottom-0 left-0 right-0 z-50 flex h-14 border-t bg-card md:hidden">
      <RouterLink to="/dashboard" title="首页" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <LayoutDashboard class="size-5" /><span>首页</span>
      </RouterLink>
      <RouterLink to="/market" title="行情" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <TrendingUp class="size-5" /><span>行情</span>
      </RouterLink>
      <RouterLink to="/portfolio" title="持仓" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <Wallet class="size-5" /><span>持仓</span>
      </RouterLink>
      <RouterLink to="/agent" title="AI对话" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <MessageSquare class="size-5" /><span>问</span>
      </RouterLink>
      <RouterLink to="/signals" title="信号" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <Bell class="size-5" /><span>信号</span>
      </RouterLink>
      <RouterLink to="/settings" title="更多" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <Settings class="size-5" /><span>更多</span>
      </RouterLink>
    </nav>
  </div>
</template>
