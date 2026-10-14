import { createRouter, createWebHistory } from 'vue-router'

// 五个页面与后端能力一一对应。
// F0 + F1 只实现「系统状态」与「岗位分析」；首页给出概览与入口，
// 「学习与项目」「成长记录」是占位页，明确标注尚未实现（不假装可用）。
const routes = [
  {
    path: '/',
    name: 'home',
    component: () => import('../views/HomeView.vue'),
    meta: { title: '职业成长首页' },
  },
  {
    path: '/analyze',
    name: 'analyze',
    component: () => import('../views/AnalyzeView.vue'),
    meta: { title: '岗位分析' },
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: () => import('../views/TasksView.vue'),
    meta: { title: '学习与项目' },
  },
  {
    path: '/growth',
    name: 'growth',
    component: () => import('../views/GrowthView.vue'),
    meta: { title: '成长记录' },
  },
  {
    path: '/status',
    name: 'status',
    component: () => import('../views/StatusView.vue'),
    meta: { title: '系统状态' },
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `${title} · AI Career Agent` : 'AI Career Agent'
})

export default router
