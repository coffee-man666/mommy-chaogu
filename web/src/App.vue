<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterView, RouterLink, useRoute } from 'vue-router'
import { LayoutDashboard, TrendingUp, Microscope, Wallet, MessageSquare, Bell, Target, Settings, ChevronRight } from 'lucide-vue-next'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'

const route = useRoute()
const moreOpen = ref(false)
const moreActive = computed(
  () =>
    route.path.startsWith('/themes') ||
    route.path.startsWith('/settings') ||
    route.path.startsWith('/predictions'),
)

function focusMainContent() {
  document.getElementById('main-content')?.focus()
}
</script>

<template>
  <div class="flex min-h-screen bg-background text-foreground">
    <a
      href="#main-content"
      class="fixed left-3 top-3 z-[100] -translate-y-20 rounded-md bg-background px-3 py-2 text-sm font-semibold shadow-lg transition-transform focus:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      @click.prevent="focusMainContent"
    >
      跳到主要内容
    </a>
    <!-- 桌面端侧边导航 -->
    <nav aria-label="主导航" class="hidden md:flex w-16 flex-col items-center gap-2 border-r bg-card py-4 sticky top-0 h-screen">
      <RouterLink to="/dashboard" title="仪表盘" aria-label="仪表盘" class="app-nav-link" active-class="!bg-primary/10 !text-primary">
        <LayoutDashboard class="size-5" aria-hidden="true" />
      </RouterLink>
      <RouterLink to="/market" title="行情" aria-label="行情" class="app-nav-link" active-class="!bg-primary/10 !text-primary">
        <TrendingUp class="size-5" aria-hidden="true" />
      </RouterLink>
      <RouterLink to="/themes" title="主题" aria-label="主题" class="app-nav-link" active-class="!bg-primary/10 !text-primary">
        <Microscope class="size-5" aria-hidden="true" />
      </RouterLink>
      <RouterLink to="/portfolio" title="持仓" aria-label="持仓" class="app-nav-link" active-class="!bg-primary/10 !text-primary">
        <Wallet class="size-5" aria-hidden="true" />
      </RouterLink>
      <RouterLink to="/agent" title="AI对话" aria-label="AI对话" class="app-nav-link" active-class="!bg-primary/10 !text-primary">
        <MessageSquare class="size-5" aria-hidden="true" />
      </RouterLink>
      <RouterLink to="/signals" title="信号" aria-label="信号" class="app-nav-link" active-class="!bg-primary/10 !text-primary">
        <Bell class="size-5" aria-hidden="true" />
      </RouterLink>
      <RouterLink to="/predictions" title="预测跟踪" aria-label="预测跟踪" class="app-nav-link" active-class="!bg-primary/10 !text-primary">
        <Target class="size-5" aria-hidden="true" />
      </RouterLink>
      <div class="flex-1" />
      <RouterLink to="/settings" title="设置" aria-label="设置" class="app-nav-link" active-class="!bg-primary/10 !text-primary">
        <Settings class="size-5" aria-hidden="true" />
      </RouterLink>
    </nav>

    <!-- 主内容区 -->
    <main id="main-content" tabindex="-1" class="mobile-main flex-1 min-w-0">
      <RouterView />
    </main>

    <!-- 移动端底部 tab -->
    <nav aria-label="移动端主导航" class="mobile-bottom-nav fixed bottom-0 left-0 right-0 z-50 flex border-t bg-card md:hidden">
      <RouterLink to="/dashboard" title="首页" aria-label="首页" class="mobile-nav-link" active-class="!text-primary font-medium">
        <LayoutDashboard class="size-5" aria-hidden="true" /><span>首页</span>
      </RouterLink>
      <RouterLink to="/market" title="行情" aria-label="行情" class="mobile-nav-link" active-class="!text-primary font-medium">
        <TrendingUp class="size-5" aria-hidden="true" /><span>行情</span>
      </RouterLink>
      <RouterLink to="/portfolio" title="持仓" aria-label="持仓" class="mobile-nav-link" active-class="!text-primary font-medium">
        <Wallet class="size-5" aria-hidden="true" /><span>持仓</span>
      </RouterLink>
      <RouterLink to="/agent" title="AI对话" aria-label="AI对话" class="mobile-nav-link" active-class="!text-primary font-medium">
        <MessageSquare class="size-5" aria-hidden="true" /><span>问</span>
      </RouterLink>
      <RouterLink to="/signals" title="信号" aria-label="信号" class="mobile-nav-link" active-class="!text-primary font-medium">
        <Bell class="size-5" aria-hidden="true" /><span>信号</span>
      </RouterLink>
      <Dialog v-model:open="moreOpen">
        <DialogTrigger as-child>
          <button
            type="button"
            class="mobile-nav-link focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset"
            :class="moreActive ? 'font-medium text-primary' : 'text-muted-foreground'"
            aria-label="打开更多导航"
          >
            <Settings class="size-5" aria-hidden="true" />
            <span>更多</span>
          </button>
        </DialogTrigger>
        <DialogContent
          class="mobile-more-dialog top-auto translate-y-0 gap-2 p-4 md:hidden"
        >
          <DialogTitle class="text-base">更多</DialogTitle>
          <DialogDescription class="sr-only">
            前往主题研究或应用设置
          </DialogDescription>
          <nav aria-label="更多导航" class="grid gap-2">
            <RouterLink
              to="/predictions"
              class="flex min-h-12 items-center gap-3 rounded-lg border px-3 py-2 text-sm font-medium transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              @click="moreOpen = false"
            >
              <Target class="size-5 text-primary" aria-hidden="true" />
              <span class="flex-1">预测跟踪</span>
              <ChevronRight class="size-4 text-muted-foreground" aria-hidden="true" />
            </RouterLink>
            <RouterLink
              to="/themes"
              class="flex min-h-12 items-center gap-3 rounded-lg border px-3 py-2 text-sm font-medium transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              @click="moreOpen = false"
            >
              <Microscope class="size-5 text-primary" aria-hidden="true" />
              <span class="flex-1">主题研究</span>
              <ChevronRight class="size-4 text-muted-foreground" aria-hidden="true" />
            </RouterLink>
            <RouterLink
              to="/settings"
              class="flex min-h-12 items-center gap-3 rounded-lg border px-3 py-2 text-sm font-medium transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              @click="moreOpen = false"
            >
              <Settings class="size-5 text-primary" aria-hidden="true" />
              <span class="flex-1">应用设置</span>
              <ChevronRight class="size-4 text-muted-foreground" aria-hidden="true" />
            </RouterLink>
          </nav>
        </DialogContent>
      </Dialog>
    </nav>
  </div>
</template>
