<script setup>
import { computed, onMounted } from 'vue'

import { AGENTS, AGENT_GROUP } from '../utils/agents'
import { useHealthStore } from '../stores/health'

/**
 * 认证页骨架：左侧品牌区 + 右侧表单区。
 *
 * 左栏只讲项目**已经做到**的事（七节点工作流、RAG 证据、本地模型），
 * 底部那行状态是真调 `/api/health`（公开接口）拿到的结果；
 * 拿不到就显示「未连接」，不写死一个绿色「就绪」。
 */
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  // 卡片头部的图标徽章（24×24 stroke 路径）；不传就不渲染徽章，只留标题
  badgeIcon: { type: String, default: '' },
})

const health = useHealthStore()

onMounted(() => {
  if (!health.data && !health.loading) health.refresh()
})

// 流水线图的数据全部来自 utils/agents.js，而它逐字对应 graph/workflow.py 的 ORDER：
// 节点名、执行顺序、四色族都不是这张图现编的。
const nodes = AGENTS.map((agent) => ({
  key: agent.node,
  label: agent.shortName,
  name: agent.displayName,
  color: AGENT_GROUP[agent.group].color,
}))

const groups = Object.entries(AGENT_GROUP).map(([key, value]) => ({ key, label: value.label, color: value.color }))

const pillars = [
  {
    key: 'agents',
    title: '七节点多 Agent 流水线',
    desc: '个人画像 → 岗位要求 → 技能差距 → 学习路线 → 项目建议，一次跑完整条链路。',
    icon: 'M12 3v4M12 17v4M5 12h4M15 12h4M8 8l8 8M16 8l-8 8',
  },
  {
    key: 'rag',
    title: 'RAG 知识库，结论可溯源',
    desc: '岗位要求逐条来自真实招聘 JD 的向量检索，附上原文出处而不是编造。',
    icon: 'M6 3h9l3 3v15H6zM9 9h6M9 13h6M9 17h4',
  },
  {
    key: 'local',
    title: '模型跑在本机',
    desc: '对话与推理由本地 Ollama 完成，简历与画像数据不出这台机器。',
    icon: 'M3 5h18v11H3zM8 20h8M12 16v4',
  },
]

const status = computed(() => {
  const data = health.data
  if (health.loading && !data) return { dot: 'dot-warn', text: '正在检测本地服务…' }
  if (health.unreachable) return { dot: 'dot-danger', text: '后端未连接：请确认 FastAPI 已在 127.0.0.1:8000 启动' }
  if (!data) return { dot: 'dot-warn', text: '服务状态未知' }
  const model = data.config?.chat_model
  if (data.status === 'ok') return { dot: 'dot-ok', text: model ? `后端与本地模型已就绪 · ${model}` : '后端与本地模型已就绪' }
  return { dot: 'dot-warn', text: '后端在线，但部分能力降级' }
})
</script>

<template>
  <div class="auth-shell">
    <section class="auth-brand">
      <div class="auth-brand-inner">
        <div class="auth-brand-head">
          <span class="auth-logo">CA</span>
          <div>
            <h1 class="auth-product">AI Career <span>Agent</span></h1>
            <p class="auth-slogan">让 AI 帮你规划下一步职业成长</p>
          </div>
        </div>

        <ul class="auth-pillars">
          <li v-for="item in pillars" :key="item.key">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path :d="item.icon" />
            </svg>
            <div>
              <strong>{{ item.title }}</strong>
              <span>{{ item.desc }}</span>
            </div>
          </li>
        </ul>

        <figure class="auth-flow">
          <figcaption>
            七节点顺序工作流
            <span class="auth-flow-src">graph/workflow.py · ORDER</span>
          </figcaption>
          <div class="auth-flow-track">
            <div v-for="node in nodes" :key="node.key" class="auth-flow-node" :title="node.name">
              <span class="auth-flow-dot" :style="{ background: node.color }" />
              <small>{{ node.label }}</small>
            </div>
          </div>
          <ul class="auth-flow-legend">
            <li v-for="group in groups" :key="group.key">
              <span class="auth-flow-swatch" :style="{ background: group.color }" />{{ group.label }}
            </li>
          </ul>
        </figure>

        <p class="auth-status">
          <span class="dot" :class="status.dot" aria-hidden="true" />{{ status.text }}
        </p>
      </div>
    </section>

    <section class="auth-panel">
      <div class="auth-form">
        <header class="auth-form-head">
          <span v-if="badgeIcon" class="auth-badge" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path :d="badgeIcon" />
            </svg>
          </span>
          <h2>{{ title }}</h2>
          <p v-if="subtitle">{{ subtitle }}</p>
        </header>

        <slot />

        <footer v-if="$slots.foot" class="auth-foot">
          <slot name="foot" />
        </footer>
      </div>
    </section>
  </div>
</template>
