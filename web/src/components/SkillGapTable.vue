<script setup>
import AgentTag from './AgentTag.vue'
import AppBadge from './AppBadge.vue'
import { formatImportance } from '../utils/format'
import { gapStatusTone, priorityTone } from '../utils/enums'

/**
 * 能力差距（agents/assessment_agent.py）。
 * 条目真实字段：{skill, status, supported_by, current_level, required_level,
 *   importance, priority, gap}
 *
 * status / priority 全部由代码判定（不是模型说的），可直接当结论展示。
 */
defineProps({
  gaps: { type: Array, default: () => [] },
  showSupportedBy: { type: Boolean, default: true },
  /** 可选的 Agent 归属标记（传节点名才显示） */
  agentNode: { type: String, default: '' },
})
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h2>
        能力差距
        <span class="sub">等级 / 状态 / 优先级由代码判定，非模型自由发挥</span>
      </h2>
      <div class="btn-row">
        <span class="badge">{{ gaps.length }} 项</span>
        <AgentTag v-if="agentNode" :node="agentNode" />
      </div>
    </div>

    <div class="card-body">
      <div v-if="!gaps.length" class="empty">没有能力差距数据。</div>

      <div v-else class="table-wrap">
        <table class="data data--gaps">
          <thead>
            <tr>
              <th>技能</th>
              <th>状态</th>
              <th>优先级</th>
              <th>当前 → 要求</th>
              <th>重要度</th>
              <th>差距说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in gaps" :key="item.skill">
              <td><strong>{{ item.skill }}</strong></td>
              <td><AppBadge :text="item.status" :tone="gapStatusTone(item.status)" /></td>
              <td><AppBadge :text="item.priority" :tone="priorityTone(item.priority)" /></td>
              <td class="muted">
                {{ item.current_level || '无' }} → {{ item.required_level || '未要求' }}
              </td>
              <td>{{ formatImportance(item.importance) }}</td>
              <td class="muted">
                {{ item.gap || '—' }}
                <div v-if="showSupportedBy && item.supported_by" class="faint">
                  依据：{{ item.supported_by }}
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>
