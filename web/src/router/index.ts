import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: () => import('../pages/index/index.vue'), name: 'dashboard' },
    { path: '/detail/:code', component: () => import('../pages/detail/index.vue'), name: 'detail', props: true },
    { path: '/signals', component: () => import('../pages/signals/index.vue'), name: 'signals' },
    { path: '/settings', component: () => import('../pages/settings/index.vue'), name: 'settings' }
  ]
})

export default router
