<script setup>
import AgentTag from './AgentTag.vue'
import { joinList } from '../utils/format'

/**
 * 学习路线（agents/learning_agent.py）。
 *
 * 只展示**业务字段**：stage / topic / goal / covers / prerequisite /
 * completion_criteria / estimated_weeks。
 * 阶段字典里还有 skill_mapping、unmapped_covers、dropped_low_priority、backfilled
 * 等内部追踪字段 —— 它们在 state 里继续保留，但不属于给用户看的内容，这里不渲染。
 */
defineProps({
  stages: { type: Array, default: () => [] },
  /** 可选的 Agent 归属标记（传节点名才显示） */
  agentNode: { type: String, default: '' },
})
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h2>
        学习路线
        <span class="sub">按岗位缺口排出的阶段顺序</span>
      </h2>
      <div class="btn-row">
        <span class="badge">{{ stages.length }} 个阶段</span>
        <AgentTag v-if="agentNode" :node="agentNode" />
      </div>
    </div>

    <div class="card-body">
      <div v-if="!stages.length" class="empty">没有生成学习路线。</div>

      <div v-else class="plan-list">
        <article v-for="stage in stages" :key="stage.stage" class="plan-stage">
          <h3 class="sub-title">
            阶段 {{ stage.stage }}：{{ stage.topic }}
            <span v-if="stage.estimated_weeks" class="badge">
              约 {{ stage.estimated_weeks }} 周
            </span>
          </h3>
          <dl class="kv">
            <dt>目标</dt>
            <dd>{{ stage.goal || '—' }}</dd>
            <dt>覆盖缺口</dt>
            <dd>{{ joinList(stage.covers) }}</dd>
            <dt>前置要求</dt>
            <dd>{{ stage.prerequisite || '无特殊前置' }}</dd>
            <dt>完成标准</dt>
            <dd>{{ stage.completion_criteria || '—' }}</dd>
          </dl>
        </article>
      </div>
    </div>
  </section>
</template>
