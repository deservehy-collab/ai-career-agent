<script setup>
import AgentTag from './AgentTag.vue'
import AppBadge from './AppBadge.vue'
import EvidenceRefChip from './EvidenceRefChip.vue'

import { formatImportance, joinList } from '../utils/format'
import {
  evidenceStatusText,
  evidenceStatusTone,
  importanceBasisText,
  importanceBasisTone,
  levelOriginText,
  levelOriginTone,
} from '../utils/enums'

/**
 * 岗位要求（agents/job_agent.py）。
 * 真实字段：{skill, importance(1~5), level, reason, evidence_status, evidence_refs[],
 *   source_companies[], importance_basis, level_basis{origin, quote, by_company}}
 *
 * 证据强度必须三态分开：
 *   supported           有直接证据
 *   partially_supported 仅弱证据（别名/语义相关），不等于完全确认
 *   model_supplement    证据里根本没有，这条是模型补充的 → 渲染成**不可点击的占位芯片**，
 *                       绝不能让它看起来像有证据
 *
 * evidence_refs 是一串 E 编号（如 ["E02","E07"]），点击后由父组件定位到证据面板的对应条目。
 */
defineProps({
  requirements: { type: Array, default: () => [] },
  /** 可选的 Agent 归属标记（传节点名才显示） */
  agentNode: { type: String, default: '' },
  /** 当前被选中的证据编号，用于芯片高亮 */
  activeRef: { type: String, default: '' },
})

const emit = defineEmits(['select-ref'])

function refsOf(item) {
  return Array.isArray(item?.evidence_refs) ? item.evidence_refs.filter(Boolean) : []
}

function levelQuote(item) {
  return item?.level_basis?.quote || ''
}
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h2>
        岗位要求
        <span class="sub">结合岗位知识库证据生成，每条都标出证据强度与出处</span>
      </h2>
      <div class="btn-row">
        <span class="badge">{{ requirements.length }} 项</span>
        <AgentTag v-if="agentNode" :node="agentNode" />
      </div>
    </div>

    <div class="card-body">
      <div v-if="!requirements.length" class="empty">没有生成岗位要求。</div>

      <div v-else class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th style="width: 180px">技能</th>
              <th style="width: 86px">重要度</th>
              <th style="width: 150px">证据强度</th>
              <th style="width: 150px">RAG 证据</th>
              <th style="width: 130px">来源公司</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in requirements" :key="item.skill">
              <td>
                <strong>{{ item.skill }}</strong>
                <div v-if="item.level" class="faint">
                  要求等级：{{ item.level }}
                  <span v-if="item.level_basis?.origin">（{{ levelOriginText(item.level_basis.origin) }}）</span>
                </div>
                <div v-if="levelQuote(item)" class="faint">原文：「{{ levelQuote(item) }}」</div>
              </td>

              <td>
                {{ formatImportance(item.importance) }}
                <div v-if="item.importance_basis" class="faint">
                  <AppBadge
                    :text="importanceBasisText(item.importance_basis)"
                    :tone="importanceBasisTone(item.importance_basis)"
                  />
                </div>
              </td>

              <td>
                <AppBadge
                  :text="evidenceStatusText(item.evidence_status)"
                  :tone="evidenceStatusTone(item.evidence_status)"
                />
              </td>

              <!-- 可追溯：编号来自 job_evidence 的数组位置，点击跳到对应证据 -->
              <td>
                <div v-if="refsOf(item).length" class="tags">
                  <EvidenceRefChip
                    v-for="code in refsOf(item)"
                    :key="code"
                    :code="code"
                    :active="activeRef === code"
                    @select="emit('select-ref', $event)"
                  />
                </div>
                <EvidenceRefChip v-else code="" placeholder="无证据支撑" />
              </td>

              <td class="muted">{{ joinList(item.source_companies, '未标注') }}</td>
              <td class="muted">{{ item.reason || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="requirements.length" class="faint" style="margin: 12px 0 0">
        点击 RAG 证据列的编号（如 E02），可跳转到下方「RAG 检索证据」中的对应原文。
        「模型补充（无知识库证据）」表示该要求**没有**知识库证据支撑，仅由模型给出。
      </p>
    </div>
  </section>
</template>
