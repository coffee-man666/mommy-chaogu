<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
import { MessageSquareText, TrendingUp, UserRound, Wallet, KeyRound } from 'lucide-vue-next'
import { authRequired } from '@/api/client'

const navigation = [
  { to: '/', label: '对话', icon: MessageSquareText },
  { to: '/market', label: '行情', icon: TrendingUp },
  { to: '/portfolio', label: '持仓', icon: Wallet },
  { to: '/my', label: '我的', icon: UserRound },
]

function focusMainContent() {
  document.getElementById('main-content')?.focus()
}
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <div
      v-if="authRequired"
      role="alert"
      class="sticky top-0 z-[90] flex items-center justify-center gap-3 bg-destructive px-4 py-2 text-sm text-white"
    >
      <KeyRound class="size-4 shrink-0" aria-hidden="true" />
      <span>需要访问令牌才能查看数据</span>
      <RouterLink to="/my" class="font-semibold underline underline-offset-2 hover:opacity-90">
        前往我的
      </RouterLink>
    </div>

    <div class="flex min-h-screen">
      <a
        href="#main-content"
        class="fixed left-3 top-3 z-[100] -translate-y-20 rounded-md bg-background px-3 py-2 text-sm font-semibold shadow-lg transition-transform focus:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        @click.prevent="focusMainContent"
      >
        跳到主要内容
      </a>

      <nav
        aria-label="主导航"
        class="sticky top-0 hidden h-screen w-40 shrink-0 flex-col border-r bg-card px-3 py-5 md:flex"
      >
        <RouterLink to="/" class="mb-6 flex items-center gap-2 px-3 text-sm font-semibold">
          <span class="flex size-8 items-center justify-center rounded-xl bg-primary text-primary-foreground">妈</span>
          <span>妈妈炒股</span>
        </RouterLink>
        <div class="space-y-1">
          <RouterLink
            v-for="item in navigation"
            :key="item.to"
            :to="item.to"
            class="flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            active-class="!bg-primary/10 !text-primary"
            :exact-active-class="item.to === '/' ? '!bg-primary/10 !text-primary' : ''"
          >
            <component :is="item.icon" class="size-5" aria-hidden="true" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </div>
      </nav>

      <main id="main-content" tabindex="-1" class="mobile-main min-w-0 flex-1">
        <RouterView />
      </main>

      <nav
        aria-label="移动端主导航"
        class="mobile-bottom-nav fixed inset-x-0 bottom-0 z-50 grid grid-cols-4 border-t bg-card md:hidden"
      >
        <RouterLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          class="mobile-nav-link min-h-14 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset"
          active-class="!text-primary font-medium"
          :exact-active-class="item.to === '/' ? '!text-primary font-medium' : ''"
        >
          <component :is="item.icon" class="size-5" aria-hidden="true" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
    </div>
  </div>
</template>
