<script setup>
import { computed } from 'vue'

import { useHealthStore } from '../stores/health'

// 顶部状态点：直接反映 /api/health 的结果，一眼看出后端/Ollama 是否就绪。
const health = useHealthStore()

const dotClass = computed(() => {
  if (health.unreachable) return 'dot dot-danger'
  if (health.status === 'ok') return 'dot dot-ok'
  return 'dot dot-warn'
})

const statusText = computed(() => {
  if (health.loading && !health.data) return '检查中…'
  if (health.unreachable) return '后端未连接'
  return health.status === 'ok' ? '就绪' : '降级运行'
})
</script>

<template>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">AI Career <span>Agent</span></div>
      <nav class="topnav">
        <router-link to="/">成长首页</router-link>
        <router-link to="/analyze">岗位分析</router-link>
        <router-link to="/tasks">学习与项目</router-link>
        <router-link to="/growth">成长记录</router-link>
        <router-link to="/status">系统状态</router-link>
      </nav>
      <span style="margin-left: auto; white-space: nowrap">
        <span :class="dotClass" />
        <span class="faint">{{ statusText }}</span>
      </span>
    </div>
  </header>
</template>
