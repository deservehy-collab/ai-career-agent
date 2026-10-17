import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'

// 页面与后端能力的对应关系：
//   /overview  概览（产品入口页，登录后的默认落地页；只发 GET，纯只读）
//   /assistant AI 助手（POST /api/chat/stream 流式对话，与工作流无关）
//   /home      我的档案（原有页面，画像与最近能力表；指标与产品介绍已收敛到 /overview）
//   /analyze   岗位分析（七节点工作流：岗位要求 / 技能差距 / 学习路线 / 项目推荐都在它的结果里）
//   /tasks     学习与项目        /growth 成长记录        /status 系统状态
const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('../views/RegisterView.vue'),
    meta: { title: '注册', public: true },
  },
  // 概览是默认页：老的 "/" 与老的 "home" 都仍在，不破坏已有链接
  { path: '/', redirect: '/overview' },
  {
    path: '/overview',
    name: 'overview',
    component: () => import('../views/OverviewView.vue'),
    meta: { title: '概览' },
  },
  {
    path: '/assistant',
    name: 'assistant',
    component: () => import('../views/AssistantView.vue'),
    meta: { title: 'AI 助手' },
  },
  {
    path: '/home',
    name: 'home',
    component: () => import('../views/HomeView.vue'),
    meta: { title: '我的档案' },
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
  // 切页回到顶部，前进/后退仍回到达记录位置。停在原滚动位置时，
  // 新页比旧页短就会露出一片空白，看着像卡住了而不是"换了页"。
  // 概览里带 #锚点 的入口也一并落到页头：结果区块要等分析跑完才存在，
  // 定位到某个节点是靠左边的流程轨（AgentPipeline 自己 scrollIntoView）。
  scrollBehavior: (to, from, saved) => saved || { top: 0 },
})

// 路由守卫：除 meta.public（登录/注册）外一律要求登录。
// 本地有 token 但本会话还没验证过有效性时，先打一次 /api/auth/me：
// token 过期/被篡改会在那里暴露（client.js 同时清掉本地登录态）。
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    // 已登录且已验证的用户不该再停留在登录/注册页
    if (auth.isLoggedIn && auth.verified) return { path: '/' }
    return true
  }

  if (!auth.isLoggedIn) {
    return { name: 'login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }

  if (!auth.verified) {
    try {
      await auth.fetchMe()
    } catch {
      auth.logout()
      return { name: 'login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
    }
  }
  return true
})

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `${title} · AI Career Agent` : 'AI Career Agent'
})

export default router
