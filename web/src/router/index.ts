import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      redirect: () => {
        // 桌面端进仪表盘，移动端进行情
        return window.innerWidth >= 768 ? '/dashboard' : '/market'
      },
    },
    {
      path: '/dashboard',
      component: () => import('../pages/dashboard/index.vue'),
      name: 'dashboard',
    },
    { path: '/market', component: () => import('../pages/market/index.vue'), name: 'market' },
    { path: '/portfolio', component: () => import('../pages/portfolio/index.vue'), name: 'portfolio' },
    { path: '/agent', component: () => import('../pages/agent/index.vue'), name: 'agent' },
    { path: '/detail/:code', component: () => import('../pages/detail/index.vue'), name: 'detail', props: true },
    { path: '/signals', component: () => import('../pages/signals/index.vue'), name: 'signals' },
    { path: '/predictions', component: () => import('../pages/predictions/index.vue'), name: 'predictions' },
    { path: '/themes', component: () => import('../pages/themes/index.vue'), name: 'themes' },
    { path: '/themes/:id', component: () => import('../pages/themes/detail.vue'), name: 'theme-detail' },
    { path: '/settings', component: () => import('../pages/settings/index.vue'), name: 'settings' },
  ],
})

export default router
