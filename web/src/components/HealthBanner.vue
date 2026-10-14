<script setup>
import { computed } from 'vue'

import { useHealthStore } from '../stores/health'

// 全局告警条：只在"真的有问题"时出现，正常时完全隐藏，不占版面。
const health = useHealthStore()

const issues = computed(() => {
  const data = health.data
  if (!data) return []
  const list = []
  if (!data.ollama?.ok) {
    list.push(`Ollama 不可达（${data.ollama?.base_url || '—'}）：分析会失败，请先启动 Ollama。`)
  } else {
    if (!data.ollama.chat_model_ready) list.push(`对话模型 ${data.ollama.chat_model} 未安装。`)
    if (!data.ollama.embedding_model_ready) list.push(`嵌入模型 ${data.ollama.embedding_model} 未安装。`)
  }
  if (!data.index?.ok) list.push('Chroma 向量索引不可用：岗位知识库检索会降级为"无证据"。')
  if (data.knowledge?.skills && !data.knowledge.skills.ok) list.push('技能知识库加载失败：升级前置门禁不会执行。')
  if (data.knowledge?.projects && !data.knowledge.projects.ok) list.push('项目知识库加载失败。')
  if (data.stores?.growth && !data.stores.growth.writable) list.push('成长记录不可安全写入，成长历史将不会被更新。')
  if (data.stores?.loop && !data.stores.loop.writable) list.push('任务记录不可安全写入，任务完成无法登记。')
  return list
})

const visible = computed(() => health.unreachable || issues.value.length > 0)
</script>

<template>
  <div v-if="visible" class="notice notice-warn">
    <strong v-if="health.unreachable">后端服务未连接</strong>
    <strong v-else>系统降级运行</strong>
    <div v-if="health.unreachable" style="margin-top: 4px">
      {{ health.errorMessage }}
    </div>
    <ul v-else>
      <li v-for="issue in issues" :key="issue">{{ issue }}</li>
    </ul>
    <div style="margin-top: 8px">
      <button class="btn" :disabled="health.loading" @click="health.refresh()">
        {{ health.loading ? '检查中…' : '重新检查' }}
      </button>
    </div>
  </div>
</template>
