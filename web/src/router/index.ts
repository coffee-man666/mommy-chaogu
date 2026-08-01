import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition ?? { top: 0 }
  },
  routes: [
    {
      path: '/',
      component: () => import('../pages/today/index.vue'),
      name: 'today',
    },
    {
      path: '/chat',
      component: () => import('../pages/chat/index.vue'),
      name: 'chat',
    },
    { path: '/agent', redirect: '/chat' },
    { path: '/dashboard', redirect: '/' },
    {
      path: '/setup',
      component: () => import('../pages/setup/index.vue'),
      name: 'setup',
    },
    { path: '/market', component: () => import('../pages/market/index.vue'), name: 'market' },
    { path: '/follow', component: () => import('../pages/follow/index.vue'), name: 'follow' },
    { path: '/portfolio', component: () => import('../pages/portfolio/index.vue'), name: 'portfolio' },
    { path: '/detail/:code', component: () => import('../pages/detail/index.vue'), name: 'detail', props: true },
    { path: '/signals', component: () => import('../pages/signals/index.vue'), name: 'signals' },
    { path: '/predictions', component: () => import('../pages/predictions/index.vue'), name: 'predictions' },
    { path: '/themes', component: () => import('../pages/themes/index.vue'), name: 'themes' },
    { path: '/themes/:id', component: () => import('../pages/themes/detail.vue'), name: 'theme-detail' },
    { path: '/baskets/:id', component: () => import('../pages/baskets/detail.vue'), name: 'basket-detail' },
    { path: '/my', component: () => import('../pages/settings/index.vue'), name: 'my' },
    { path: '/settings', redirect: '/my' },
    { path: '/:pathMatch(.*)*', component: () => import('../pages/NotFound.vue'), name: 'not-found' },
  ],
})

export default router
