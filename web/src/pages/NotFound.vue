<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { Compass } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
</script>

<template>
  <section class="flex min-h-[70dvh] items-center justify-center p-6 text-center">
    <div class="max-w-sm space-y-4">
      <Compass class="mx-auto size-10 text-muted-foreground" aria-hidden="true" />
      <div>
        <h1 class="text-2xl font-bold">页面走丢了</h1>
        <p class="mt-2 text-sm text-muted-foreground">这个地址不存在，回到首页看看今天行情吧。</p>
      </div>
      <Button as-child>
        <RouterLink to="/">回到首页</RouterLink>
      </Button>
    </div>
  </section>
</template>
