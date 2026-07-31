<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { MessageSquareText, LayoutGrid, Star, UserRound, Wallet, KeyRound } from 'lucide-vue-next'
import { authRequired, loadAuthStatus, authMode } from '@/api/client'
import { getSetupStatus } from '@/api/setup'
import BrandMark from '@/components/BrandMark.vue'

const route = useRoute()
const router = useRouter()

// 导航：今日 / 关注 / 持仓 / 问AI（移动端 4 tab）
const navigation = [
  { to: '/', label: '今日', icon: LayoutGrid },
  { to: '/follow', label: '关注', icon: Star },
  { to: '/portfolio', label: '持仓', icon: Wallet },
  { to: '/chat', label: '问AI', icon: MessageSquareText },
]

/** When true, the full app shell is hidden (no flash of protected UI). */
const bootstrapping = ref(true)
const bootstrapError = ref('')

/** /setup renders outside the normal app shell. */
const isSetupRoute = computed(() => route.path === '/setup')

function focusMainContent() {
  document.getElementById('main-content')?.focus()
}

async function bootstrap() {
  bootstrapping.value = true
  bootstrapError.value = ''
  try {
    const auth = await loadAuthStatus()

    // If not authenticated and auth is required, redirect to /setup.
    // Do NOT call any /api/setup/* endpoint — they would 401.
    if (!auth.authenticated && auth.mode !== 'none') {
      if (!isSetupRoute.value) {
        await router.replace({ path: '/setup', query: { returnTo: route.fullPath } })
      }
      bootstrapping.value = false
      return
    }

    // Authenticated or no-auth mode — safe to check LLM config.
    if (auth.authenticated || auth.mode === 'none') {
      try {
        const status = await getSetupStatus()
        if (!status.llm_configured && !isSetupRoute.value) {
          await router.replace({ path: '/setup', query: { returnTo: route.fullPath } })
          bootstrapping.value = false
          return
        }
      } catch {
        // Setup status may fail — don't block the app
      }
    }
  } catch (error) {
    console.warn('认证模式检查失败', error)
    bootstrapError.value = '无法连接本地服务，请确认服务正在运行后重试。'
  }
  bootstrapping.value = false
}

onMounted(() => {
  bootstrap()
})
</script>

<template>
  <!-- Bootstrap overlay: prevents flash of protected UI before auth check completes -->
  <div v-if="bootstrapping && !isSetupRoute" class="flex min-h-screen items-center justify-center bg-background">
    <div class="text-center">
      <BrandMark alt="" size="md" class="mx-auto mb-3" />
      <p class="text-sm text-muted-foreground">正在连接…</p>
    </div>
  </div>

  <div v-else-if="bootstrapError && !isSetupRoute" class="flex min-h-screen items-center justify-center bg-background p-6">
    <div class="max-w-sm space-y-4 text-center" role="alert">
      <BrandMark alt="" size="md" class="mx-auto" />
      <div class="space-y-1">
        <h1 class="text-lg font-semibold text-balance">暂时无法打开应用</h1>
        <p class="text-sm text-muted-foreground text-pretty">{{ bootstrapError }}</p>
      </div>
      <button
        type="button"
        class="inline-flex min-h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
        @click="bootstrap"
      >
        重新连接
      </button>
    </div>
  </div>

  <!-- Setup route renders outside the normal app shell -->
  <RouterView v-else-if="isSetupRoute" />

  <!-- Normal app shell -->
  <div v-else class="min-h-screen bg-background text-foreground">
    <div
      v-if="authRequired && authMode !== 'pairing'"
      role="alert"
      class="sticky top-0 z-[90] flex items-center justify-center gap-3 bg-destructive px-4 py-2 text-sm text-white"
    >
      <KeyRound class="size-4 shrink-0" aria-hidden="true" />
      <span>需要访问令牌才能查看数据</span>
      <RouterLink to="/setup" class="font-semibold underline underline-offset-2 hover:opacity-90">
        前往配置
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
        <RouterLink
          to="/"
          aria-label="返回妈妈炒股首页"
          class="mb-6 flex items-center gap-2 rounded-xl px-2 py-1.5 text-sm font-semibold transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <BrandMark alt="" size="md" />
          <span class="min-w-0">
            <span class="block truncate">妈妈炒股</span>
            <span class="block truncate text-[10px] font-normal text-muted-foreground">AI 投研 Agent</span>
          </span>
        </RouterLink>
        <div class="flex-1 space-y-1">
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
        <!-- 我的：桌面端侧栏底部 -->
        <div class="mt-auto border-t pt-3">
          <RouterLink
            to="/my"
            class="flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            active-class="!bg-primary/10 !text-primary"
          >
            <UserRound class="size-5" aria-hidden="true" />
            <span>我的</span>
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
