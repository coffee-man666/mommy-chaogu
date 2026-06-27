<script setup lang="ts">
import { onLaunch, onShow } from '@tarojs/taro'

onLaunch(() => {
  console.log('mommy-chaogu launched')
})

onShow(() => {
  console.log('mommy-chaogu shown')
})
</script>

<template>
  <router-view />
</template>

<style>
/* 全局样式 */
page {
  background: #f5f5f5;
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Helvetica, "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 28rpx;
  color: #333;
  line-height: 1.5;
}

/* H5 适配 */
@media (max-width: 768px) {
  page { font-size: 14px; }
}
</style>
