<script setup>
import { onMounted } from 'vue'

import AppNav from './components/AppNav.vue'
import HealthBanner from './components/HealthBanner.vue'
import { useHealthStore } from './stores/health'

// 应用启动先体检一次：后续所有页面的可用性判断都基于这份结果。
const health = useHealthStore()
onMounted(() => {
  if (!health.data && !health.loading) health.refresh()
})
</script>

<template>
  <div class="layout">
    <AppNav />
    <main class="layout-main">
      <HealthBanner />
      <router-view />
    </main>
  </div>
</template>
