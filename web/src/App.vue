<script setup lang="ts">
import { RouterView, RouterLink } from 'vue-router'
import { LayoutDashboard, TrendingUp, Microscope, Wallet, MessageSquare, Bell, Settings } from 'lucide-vue-next'
import { cn } from '@/lib/utils'
</script>

<template>
  <div class="flex min-h-screen bg-background text-foreground">
    <!-- 桌面端侧边导航 -->
    <nav class="hidden md:flex w-16 flex-col items-center gap-2 border-r bg-card py-4 sticky top-0 h-screen">
      <RouterLink to="/dashboard" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <LayoutDashboard class="size-5" />
      </RouterLink>
      <RouterLink to="/market" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <TrendingUp class="size-5" />
      </RouterLink>
      <RouterLink to="/themes" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <Microscope class="size-5" />
      </RouterLink>
      <RouterLink to="/portfolio" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <Wallet class="size-5" />
      </RouterLink>
      <RouterLink to="/agent" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <MessageSquare class="size-5" />
      </RouterLink>
      <RouterLink to="/signals" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <Bell class="size-5" />
      </RouterLink>
      <div class="flex-1" />
      <RouterLink to="/settings" class="flex h-11 w-11 items-center justify-center rounded-xl text-muted-foreground hover:bg-accent hover:text-foreground transition-colors" active-class="!bg-primary/10 !text-primary">
        <Settings class="size-5" />
      </RouterLink>
    </nav>

    <!-- 主内容区 -->
    <main class="flex-1 min-w-0 pb-16 md:pb-0">
      <RouterView />
    </main>

    <!-- 移动端底部 tab -->
    <nav class="fixed bottom-0 left-0 right-0 z-50 flex h-14 border-t bg-card md:hidden">
      <RouterLink to="/market" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <TrendingUp class="size-5" /><span>行情</span>
      </RouterLink>
      <RouterLink to="/themes" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <Microscope class="size-5" /><span>主题</span>
      </RouterLink>
      <RouterLink to="/portfolio" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <Wallet class="size-5" /><span>持仓</span>
      </RouterLink>
      <RouterLink to="/agent" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <MessageSquare class="size-5" /><span>问</span>
      </RouterLink>
      <RouterLink to="/settings" class="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground" active-class="!text-primary font-medium">
        <Settings class="size-5" /><span>设置</span>
      </RouterLink>
    </nav>
  </div>
</template>
