<script setup>
import AgentTag from './AgentTag.vue'
import { joinList } from '../utils/format'

/**
 * 项目路线（agents/project_agent.py）。
 * 条目业务字段：name / goal / covers_gaps / tech_stack / stage / deliverable。
 * difficulty、blocked_reason 等由知识库/校验环节按需附加，有就展示、没有就不显示。
 */
defineProps({
  projects: { type: Array, default: () => [] },
  /** 可选的 Agent 归属标记（传节点名才显示） */
  agentNode: { type: String, default: '' },
})
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h2>
        项目路线
        <span class="sub">用实战项目补齐岗位缺口</span>
      </h2>
      <div class="btn-row">
        <span class="badge">{{ projects.length }} 个项目</span>
        <AgentTag v-if="agentNode" :node="agentNode" />
      </div>
    </div>

    <div class="card-body">
      <div v-if="!projects.length" class="empty">没有生成项目建议。</div>

      <div v-else class="grid grid-2">
        <article
          v-for="project in projects"
          :key="project.name"
          class="card"
          style="margin: 0; box-shadow: none"
        >
          <div class="card-body">
            <h3 style="font-size: 14px">
              {{ project.name }}
              <span v-if="project.difficulty" class="badge" style="margin-left: 6px">
                {{ project.difficulty }}
              </span>
            </h3>
            <dl class="kv" style="margin-top: 8px; grid-template-columns: 88px 1fr">
              <dt>目标</dt>
              <dd>{{ project.goal || '—' }}</dd>
              <dt>对应缺口</dt>
              <dd>{{ joinList(project.covers_gaps) }}</dd>
              <dt>技术栈</dt>
              <dd>{{ joinList(project.tech_stack) }}</dd>
              <dt>对应阶段</dt>
              <dd>{{ project.stage || '—' }}</dd>
              <dt>最终成果</dt>
              <dd>{{ project.deliverable || '—' }}</dd>
            </dl>
            <div v-if="project.blocked_reason" class="notice notice-warn" style="margin: 10px 0 0">
              {{ project.blocked_reason }}
            </div>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>
