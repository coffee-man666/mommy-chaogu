<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { loadAuthStatus } from '@/api/client'
import {
  getSetupStatus,
  getSetupProviders,
  validateProvider,
  saveProvider,
  startWeixinPairing,
  pollWeixinPairing,
  submitPairingCode,
} from '@/api/setup'
import type { SetupProvider, WeixinStatus } from '@/api/setup'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import BrandMark from '@/components/BrandMark.vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const route = useRoute()
const router = useRouter()

// ---------- Bootstrap: determine which steps to show ----------
const loading = ref(true)
const step = ref<'pairing' | 'legacy' | 'ai' | 'weixin'>('ai')
const bootstrapError = ref('')

const providers = ref<SetupProvider[]>([])

// ---------- AI config form ----------
const selectedProvider = ref('')
const model = ref('')
const apiKey = ref('')
const showKey = ref(false)
const validating = ref(false)
const saving = ref(false)
const aiMessage = ref('')
const aiError = ref('')

function onProviderChange(id: string) {
  selectedProvider.value = id
  const p = providers.value.find((p) => p.id === id)
  if (p) model.value = p.default_model
}

async function doValidate() {
  aiError.value = ''
  aiMessage.value = ''
  if (!selectedProvider.value || !model.value.trim() || !apiKey.value.trim()) {
    aiError.value = '请先完整填写服务商、模型和 API Key'
    return
  }
  validating.value = true
  try {
    const result = await validateProvider(selectedProvider.value, model.value, apiKey.value)
    if (result.ok) {
      aiMessage.value = result.message
    } else {
      aiError.value = result.message
    }
  } catch (e: unknown) {
    aiError.value = (e as Error).message || '验证失败'
  } finally {
    validating.value = false
  }
}

async function doSave() {
  aiError.value = ''
  aiMessage.value = ''
  if (!selectedProvider.value || !model.value.trim() || !apiKey.value.trim()) {
    aiError.value = '请先完整填写服务商、模型和 API Key'
    return
  }
  saving.value = true
  try {
    const result = await saveProvider(selectedProvider.value, model.value, apiKey.value)
    if (result.ok) {
      aiMessage.value = result.message
      apiKey.value = '' // Never store the key after save
      // Move to weixin step unless an explicit step=ai was requested
      const explicitStep = route.query.step
      if (explicitStep === 'ai') {
        // User came from /my reconfigure — go back
        finishSetup()
      } else {
        step.value = 'weixin'
      }
    } else {
      aiError.value = result.message
    }
  } catch (e: unknown) {
    aiError.value = (e as Error).message || '保存失败'
  } finally {
    saving.value = false
  }
}

// ---------- Remote pairing ----------
const pairingCode = ref('')
const pairingError = ref('')
const pairingSubmitting = ref(false)

const canSubmitCode = computed(() => /^\d{6}$/.test(pairingCode.value))

function sanitizePairingInput() {
  // Keep only ASCII digits, max 6
  pairingCode.value = pairingCode.value.replace(/[^\d]/g, '').slice(0, 6)
}

async function doPair() {
  pairingError.value = ''
  if (!canSubmitCode.value) {
    pairingError.value = '请输入 6 位数字'
    return
  }
  pairingSubmitting.value = true
  try {
    const result = await submitPairingCode(pairingCode.value)
    if (result.ok) {
      pairingCode.value = '' // Clear immediately
      // Reload auth status to pick up the cookie, then bootstrap
      await loadAuthStatus()
      await bootstrap()
    } else {
      pairingError.value = result.message
      pairingCode.value = ''
    }
  } catch {
    pairingError.value = '配对失败，请重试'
    pairingCode.value = ''
  } finally {
    pairingSubmitting.value = false
  }
}

// ---------- Weixin step ----------
const weixinStarted = ref(false)
const weixinQrUrl = ref('')
const weixinPairingId = ref('')
const weixinStatus = ref<WeixinStatus>('waiting')
const weixinMessage = ref('')
const weixinVerifyCode = ref('')
const weixinShowVerify = ref(false)
const weixinPolling = ref(false)
const weixinStarting = ref(false)
const weixinVerifySubmitting = ref(false)
let weixinTimer: number | null = null

const canSubmitVerify = computed(() => /^[0-9]{1,8}$/.test(weixinVerifyCode.value))

function sanitizeVerifyInput() {
  weixinVerifyCode.value = weixinVerifyCode.value.replace(/[^0-9]/g, '').slice(0, 8)
}

function resetWeixinState() {
  stopWeixinPolling()
  weixinStarted.value = false
  weixinQrUrl.value = ''
  weixinPairingId.value = ''
  weixinStatus.value = 'waiting'
  weixinMessage.value = ''
  weixinVerifyCode.value = ''
  weixinShowVerify.value = false
}

async function startWeixin() {
  if (weixinStarting.value) return
  stopWeixinPolling()
  weixinStarting.value = true
  weixinStarted.value = true
  weixinStatus.value = 'waiting'
  weixinMessage.value = ''
  weixinQrUrl.value = ''
  weixinPairingId.value = ''
  weixinShowVerify.value = false
  weixinVerifyCode.value = ''
  try {
    const result = await startWeixinPairing()
    if (result.status === 'error') {
      weixinStatus.value = 'error'
      weixinMessage.value = result.message
      return
    }
    if (result.status === 'connected' || result.status === 'already_connected') {
      weixinStatus.value = result.status
      weixinMessage.value = result.message
      return
    }
    weixinQrUrl.value = result.qr_data_url
    weixinPairingId.value = result.pairing_id
    weixinMessage.value = result.message
    startWeixinPolling()
  } catch {
    weixinStatus.value = 'error'
    weixinMessage.value = '获取二维码失败，请重试'
  } finally {
    weixinStarting.value = false
  }
}

function startWeixinPolling() {
  stopWeixinPolling()
  weixinTimer = window.setInterval(pollWeixinOnce, 3000)
}

function stopWeixinPolling() {
  if (weixinTimer !== null) {
    clearInterval(weixinTimer)
    weixinTimer = null
  }
}

async function pollWeixinOnce(verifyCode?: string): Promise<boolean> {
  if (!weixinPairingId.value || weixinPolling.value) return false
  if (['connected', 'already_connected', 'expired', 'error'].includes(weixinStatus.value)) {
    stopWeixinPolling()
    return false
  }
  // Stop polling when verification is required — wait for explicit submit
  if (weixinShowVerify.value && verifyCode === undefined) return false

  weixinPolling.value = true
  try {
    // Only send verify_code when explicitly submitted; otherwise send empty
    const code = verifyCode ?? ''
    const result = await pollWeixinPairing(weixinPairingId.value, code)
    weixinStatus.value = result.status
    weixinMessage.value = result.message
    if (result.status === 'connected') {
      stopWeixinPolling()
    } else if (result.status === 'already_connected') {
      stopWeixinPolling()
    } else if (result.status === 'verification_required') {
      stopWeixinPolling() // Stop auto-poll; wait for explicit verify submit
      weixinShowVerify.value = true
    } else if (result.status === 'expired' || result.status === 'error') {
      stopWeixinPolling()
    }
    return true
  } catch {
    weixinMessage.value = verifyCode === undefined
      ? '暂时无法查询扫码状态，正在重试…'
      : '验证码提交失败，请检查连接后重试'
    return false
  } finally {
    weixinPolling.value = false
  }
}

async function submitVerifyCode() {
  if (weixinVerifySubmitting.value) return
  if (!canSubmitVerify.value) {
    weixinMessage.value = '请输入手机微信显示的 1–8 位数字验证码'
    return
  }
  stopWeixinPolling()
  weixinVerifySubmitting.value = true
  const submitted = await pollWeixinOnce(weixinVerifyCode.value)
  weixinVerifySubmitting.value = false

  if (!submitted) {
    weixinShowVerify.value = true
    return
  }

  weixinVerifyCode.value = ''
  if (weixinStatus.value === 'verification_required') {
    weixinShowVerify.value = true
  } else if (!['connected', 'already_connected', 'expired', 'error'].includes(weixinStatus.value)) {
    weixinShowVerify.value = false
    startWeixinPolling()
  }
}

function retryWeixin() {
  resetWeixinState()
  startWeixin()
}

function skipWeixin() {
  resetWeixinState()
  finishSetup()
}

function finishSetup() {
  const rawReturnTo = route.query.returnTo
  const returnTo = typeof rawReturnTo === 'string' ? rawReturnTo : '/'
  if (!returnTo.startsWith('/') || returnTo.startsWith('//')) {
    router.replace('/')
    return
  }
  const resolved = router.resolve(returnTo)
  const isKnownRoute = resolved.matched.some((match) => match.name !== 'not-found')
  router.replace(isKnownRoute && resolved.path !== '/setup' ? resolved.fullPath : '/')
}

// ---------- Bootstrap ----------
async function bootstrap() {
  loading.value = true
  bootstrapError.value = ''

  // Call loadAuthStatus first. If unauthenticated in pairing/token
  // mode, render the pairing/legacy step immediately and DO NOT call any
  // /api/setup/* endpoint (those would 401).
  let isAuthed = false
  let authMode = 'none'
  try {
    const auth = await loadAuthStatus()
    isAuthed = auth.authenticated
    authMode = auth.mode
  } catch {
    bootstrapError.value = '无法连接本地服务，请确认服务正在运行后重试。'
    loading.value = false
    return
  }

  if (!isAuthed && (authMode === 'pairing' || authMode === 'token')) {
    step.value = authMode === 'pairing' ? 'pairing' : 'legacy'
    loading.value = false
    return
  }

  // Authenticated or no-auth — safe to call setup APIs
  try {
    const status = await getSetupStatus()

    // Explicit query parameters provide stable reconfiguration entry points.
    const explicitStep = typeof route.query.step === 'string' ? route.query.step : undefined
    if (explicitStep === 'ai') {
      step.value = 'ai'
      await loadProviders(status)
      loading.value = false
      return
    }
    if (explicitStep === 'weixin') {
      step.value = 'weixin'
      loading.value = false
      return
    }

    if (!status.llm_configured) {
      step.value = 'ai'
      await loadProviders(status)
    } else if (!status.weixin.connected) {
      step.value = 'weixin'
    } else {
      finishSetup()
      return
    }
  } catch {
    bootstrapError.value = '读取配置状态失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

async function loadProviders(status: { provider: string; model: string } | null) {
  try {
    const prods = await getSetupProviders()
    providers.value = prods
    if (prods.length === 0) {
      bootstrapError.value = '当前没有可用的 AI 服务商配置。'
      return
    }
    selectedProvider.value = status?.provider || prods[0].id
    const match = prods.find((p) => p.id === selectedProvider.value)
    model.value = status?.model || match?.default_model || ''
  } catch {
    bootstrapError.value = '读取 AI 服务商列表失败，请稍后重试。'
  }
}

onMounted(() => {
  bootstrap()
})

watch(
  () => [route.query.step, route.query.returnTo],
  () => {
    resetWeixinState()
    bootstrap()
  },
)

onUnmounted(() => {
  stopWeixinPolling()
})
</script>

<template>
  <main class="min-h-screen overflow-x-hidden bg-muted/30 px-4 py-6 sm:py-10">
    <header class="mx-auto mb-5 flex w-full max-w-2xl items-center gap-3">
      <BrandMark alt="" size="md" class="shrink-0" />
      <div class="min-w-0">
        <p class="text-sm font-semibold text-primary">妈妈炒股</p>
        <h1 class="text-xl font-bold tracking-tight text-balance">一次配置，之后直接使用</h1>
        <p class="text-sm text-muted-foreground text-pretty">密钥只保存在这台设备；微信扫码仅用于连接消息通道。</p>
      </div>
    </header>

    <ol
      v-if="!loading && !bootstrapError && (step === 'ai' || step === 'weixin')"
      aria-label="配置进度"
      class="mx-auto mb-4 grid w-full max-w-2xl grid-cols-2 gap-2 text-sm"
    >
      <li
        class="rounded-lg border px-3 py-2"
        :class="step === 'ai' ? 'border-primary bg-primary/5 font-semibold text-primary' : 'bg-card text-muted-foreground'"
        :aria-current="step === 'ai' ? 'step' : undefined"
      >
        1 · AI 助手
      </li>
      <li
        class="rounded-lg border px-3 py-2"
        :class="step === 'weixin' ? 'border-primary bg-primary/5 font-semibold text-primary' : 'bg-card text-muted-foreground'"
        :aria-current="step === 'weixin' ? 'step' : undefined"
      >
        2 · 微信（可选）
      </li>
    </ol>

    <div class="mx-auto w-full max-w-2xl space-y-4">
    <!-- Loading -->
    <div v-if="loading" class="flex min-h-[40vh] items-center justify-center" aria-live="polite">
      <p class="text-muted-foreground">正在检查配置…</p>
    </div>

    <Card v-else-if="bootstrapError" role="alert">
      <CardHeader>
        <CardTitle as="h2" class="text-lg text-balance">暂时无法读取配置</CardTitle>
        <CardDescription class="text-pretty">{{ bootstrapError }}</CardDescription>
      </CardHeader>
      <CardContent>
        <Button @click="bootstrap">重新连接</Button>
      </CardContent>
    </Card>

    <template v-else>
      <!-- Step: Remote pairing -->
      <template v-if="step === 'pairing'">
        <Card>
          <CardHeader>
            <CardTitle as="h2" class="text-lg text-balance">输入配对码</CardTitle>
            <CardDescription>
              在服务启动时控制台打印了 6 位配对码，输入后即可安全访问
            </CardDescription>
          </CardHeader>
          <Separator />
          <CardContent class="pt-4">
            <form class="space-y-4" @submit.prevent="doPair">
              <div class="space-y-2">
                <label for="pairing-code" class="text-sm font-medium">配对码（6 位数字）</label>
              <Input
                id="pairing-code"
                v-model="pairingCode"
                name="pairing-code"
                inputmode="numeric"
                autocomplete="one-time-code"
                spellcheck="false"
                maxlength="6"
                placeholder="例如 123456…"
                aria-label="6 位配对码"
                :aria-invalid="Boolean(pairingError)"
                aria-describedby="pairing-help pairing-error"
                class="text-center text-2xl tracking-[0.5em]"
                @input="sanitizePairingInput"
              />
                <p id="pairing-help" class="text-xs text-muted-foreground">配对码显示在服务启动终端中，无需复制访问令牌。</p>
              </div>
              <p id="pairing-error" class="min-h-5 text-sm text-destructive" aria-live="polite">{{ pairingError }}</p>
              <Button type="submit" :disabled="pairingSubmitting" class="w-full">
                {{ pairingSubmitting ? '配对中…' : '完成配对' }}
              </Button>
            </form>
          </CardContent>
        </Card>
      </template>

      <!-- Step: Legacy token guidance -->
      <template v-if="step === 'legacy'">
        <Card>
          <CardHeader>
            <CardTitle as="h2" class="text-lg text-balance">需要认证</CardTitle>
            <CardDescription>当前服务以令牌模式运行</CardDescription>
          </CardHeader>
          <Separator />
          <CardContent class="space-y-3 pt-4">
            <p class="text-sm text-muted-foreground">
              此服务仍在使用旧令牌模式。请重启 Web 服务，终端会显示一次性 6 位配对码。
            </p>
          </CardContent>
        </Card>
      </template>

      <!-- Step: AI config -->
      <template v-if="step === 'ai'">
        <Card>
          <CardHeader>
            <CardTitle as="h2" class="text-lg text-balance">配置 AI 助手</CardTitle>
            <CardDescription>选择服务商并填入 API Key；保存前会先验证是否可用。</CardDescription>
          </CardHeader>
          <Separator />
          <CardContent class="space-y-4 pt-4">
            <!-- Provider -->
            <div class="space-y-2">
              <label for="provider-select" class="text-sm font-medium">服务商</label>
              <Select :model-value="selectedProvider" @update:model-value="(v) => onProviderChange(String(v))">
                <SelectTrigger id="provider-select">
                  <SelectValue placeholder="选择服务商" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="p in providers" :key="p.id" :value="p.id">
                    {{ p.label }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <!-- Model -->
            <div class="space-y-2">
              <label for="model-input" class="text-sm font-medium">模型</label>
              <Input
                id="model-input"
                v-model="model"
                name="model"
                autocomplete="off"
                spellcheck="false"
                placeholder="例如 deepseek-chat…"
                aria-label="模型名称"
              />
            </div>

            <!-- API Key -->
            <div class="space-y-2">
              <label for="key-input" class="text-sm font-medium">API Key</label>
              <div class="flex gap-2">
                <Input
                  id="key-input"
                  v-model="apiKey"
                  name="api-key"
                  :type="showKey ? 'text' : 'password'"
                  autocomplete="new-password"
                  spellcheck="false"
                  placeholder="粘贴 API Key…"
                  aria-label="API Key"
                  class="flex-1"
                />
                <Button type="button" variant="outline" size="sm" @click="showKey = !showKey">
                  {{ showKey ? '隐藏' : '显示' }}
                </Button>
              </div>
            </div>

            <!-- Messages -->
            <div aria-live="polite">
              <p v-if="aiError" class="text-sm text-destructive">{{ aiError }}</p>
              <p v-if="aiMessage" class="text-sm text-green-600 dark:text-green-400">{{ aiMessage }}</p>
            </div>

            <!-- Actions -->
            <div class="flex gap-2">
              <Button type="button" variant="outline" :disabled="validating || saving" @click="doValidate">
                {{ validating ? '验证中…' : '验证' }}
              </Button>
              <Button type="button" :disabled="saving || validating" @click="doSave">
                {{ saving ? '保存中…' : '保存 AI 配置' }}
              </Button>
            </div>
          </CardContent>
        </Card>
      </template>

      <!-- Step: Weixin (optional) -->
      <template v-if="step === 'weixin'">
        <Card>
          <CardHeader>
            <CardTitle as="h2" class="text-lg text-balance">连接微信消息通道</CardTitle>
            <CardDescription>
              连接微信消息通道，让你可以在微信里与 Agent 对话，不用于 Web 登录。
            </CardDescription>
          </CardHeader>
          <Separator />
          <CardContent class="space-y-4 pt-4">
            <!-- Not started -->
            <div v-if="!weixinStarted" class="space-y-3">
              <p class="text-sm text-muted-foreground">连接后即可在微信中直接与 AI 助手对话。</p>
              <div class="flex gap-2">
                <Button :disabled="weixinStarting" @click="startWeixin">
                  {{ weixinStarting ? '正在获取二维码…' : '显示微信二维码' }}
                </Button>
                <Button variant="outline" @click="skipWeixin">以后再说</Button>
              </div>
            </div>

            <!-- QR display + waiting/scanned -->
            <template v-if="weixinStarted && !['connected', 'already_connected'].includes(weixinStatus)">
              <p v-if="weixinStarting" class="text-sm text-muted-foreground" aria-live="polite">正在获取二维码…</p>
              <div v-if="weixinQrUrl" class="flex flex-col items-center gap-3">
                <img :src="weixinQrUrl" alt="微信二维码" width="192" height="192" class="size-48 rounded-lg border" />
                <p class="text-sm text-muted-foreground text-pretty" aria-live="polite">{{ weixinMessage || '请用微信扫描二维码' }}</p>
              </div>

              <!-- Verification code input (stops auto-poll, waits for explicit submit) -->
              <form v-if="weixinShowVerify" class="space-y-2" @submit.prevent="submitVerifyCode">
                <label for="verify-code" class="text-sm font-medium">微信验证码</label>
                <div class="flex flex-wrap gap-2">
                  <Input
                    id="verify-code"
                    v-model="weixinVerifyCode"
                    name="weixin-verify-code"
                    inputmode="numeric"
                    autocomplete="one-time-code"
                    spellcheck="false"
                    maxlength="8"
                    placeholder="手机微信显示的数字…"
                    aria-label="微信验证码"
                    class="max-w-[220px]"
                    @input="sanitizeVerifyInput"
                  />
                  <Button type="submit" variant="outline" :disabled="weixinVerifySubmitting">
                    {{ weixinVerifySubmitting ? '提交中…' : '提交验证码' }}
                  </Button>
                </div>
              </form>

              <!-- Error/expired retry -->
              <div v-if="weixinStatus === 'error' || weixinStatus === 'expired'" class="space-y-2">
                <p class="text-sm text-destructive text-pretty" role="alert">{{ weixinMessage }}</p>
                <Button variant="outline" size="sm" @click="retryWeixin">重试</Button>
              </div>

              <Button v-if="weixinStatus !== 'error' && weixinStatus !== 'expired'" variant="outline" @click="skipWeixin">以后再说</Button>
            </template>

            <!-- Connected -->
            <div v-if="weixinStatus === 'connected'" class="space-y-3">
              <Badge class="bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300">已连接</Badge>
              <p class="text-sm">{{ weixinMessage }}</p>
              <Button @click="finishSetup">完成</Button>
            </div>

            <!-- Already connected -->
            <div v-if="weixinStatus === 'already_connected'" class="space-y-3">
              <Badge variant="secondary">已绑定</Badge>
              <p class="text-sm text-muted-foreground">{{ weixinMessage }}</p>
              <Button variant="outline" @click="finishSetup">完成</Button>
            </div>
          </CardContent>
        </Card>
      </template>
    </template>
    </div>
  </main>
</template>
