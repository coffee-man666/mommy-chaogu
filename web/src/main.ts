import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'
// 主题初始化（模块加载即触发：读 localStorage、加 .dark class）。
// 必须在 App mount 前执行，否则首屏会闪一下浅色。
import './composables/useTheme'

createApp(App).use(createPinia()).use(router).mount('#app')
