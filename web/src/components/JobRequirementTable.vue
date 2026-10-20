<script setup>
import { computed } from 'vue'

import AgentTag from './AgentTag.vue'
import AppBadge from './AppBadge.vue'
import EvidenceRefChip from './EvidenceRefChip.vue'

import { formatImportance } from '../utils/format'
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
 *   importance_basis, level_basis{origin, quote, by_company},
 *   source_notes[]（本条要求反查到的原话句子）}
 *
 * 证据强度必须三态分开：
 *   supported           原话里逐字写着这个技能
 *   partially_supported 只靠别名/语义对上，强度弱于前者
 *   model_supplement    原话里根本没有，这条是模型补充的 → 渲染成**不可点击的占位芯片**，
 *                       绝不能让它看起来像有证据
 *
 * evidence_refs 是一串 E 编号（如 ["E02","E07"]），点击后由父组件定位到原文面板的对应句子。
 *
 * basis（两档，见 utils/enums REQUIREMENT_BASIS）决定"依据"一列摆什么：
 *   user_pasted  用户当场粘贴的招聘要求原文 → 直接反显原话
 *   model_only   没有原文 → 整栏标灰，说明这条只是模型推测
 */
const props = defineProps({
  requirements: { type: Array, default: () => [] },
  /** 可选的 Agent 归属标记（传节点名才显示） */
  agentNode: { type: String, default: '' },
  /** 当前被选中的证据编号，用于芯片高亮 */
  activeRef: { type: String, default: '' },
  /** 本次岗位要求的主依据档位 */
  basis: { type: String, default: 'model_only' },
})

const emit = defineEmits(['select-ref'])

const isUserJd = computed(() => props.basis === 'user_pasted')
const isGuesswork = computed(() => props.basis === 'model_only')

const basisColumnLabel = computed(() => (isUserJd.value ? '你粘的原话' : '依据'))

/** 没有原话时那句实话 —— 两档各有各的说法，不能统一写成"无证据"糊过去。 */
const noSourceHint = computed(() =>
  isUserJd.value ? '招聘要求里没有这句话，是模型自己加的' : '没有任何依据材料',
)

function refsOf(item) {
  return Array.isArray(item?.evidence_refs) ? item.evidence_refs.filter(Boolean) : []
}

/** 本条要求反查到的原话句子。 */
function notesOf(item) {
  return (Array.isArray(item?.source_notes) ? item.source_notes : []).filter(Boolean)
}

/** 一格里最多摆 3 句原话，多了折叠成计数 —— 表格不能被一句话撑爆。 */
function shownNotes(item) {
  return notesOf(item).slice(0, 3)
}

function levelQuote(item) {
  return item?.level_basis?.quote || ''
}
</script>

<template>
  <section class="card" :class="{ 'is-uncertain': isGuesswork }">
    <div class="card-head">
      <h2>
        岗位要求
        <span class="sub">
          {{
            isUserJd
              ? '逐条从你粘贴的招聘要求原文里得出，右侧直接摆出对应原话'
              : '没有粘贴招聘要求原文，以下是模型推测，只能当思路参考'
          }}
        </span>
      </h2>
      <div class="btn-row">
        <span class="badge">{{ requirements.length }} 项</span>
        <AgentTag v-if="agentNode" :node="agentNode" />
      </div>
    </div>

    <div class="card-body">
      <div v-if="!requirements.length" class="empty">没有生成岗位要求。</div>

      <div v-else class="table-wrap">
        <table class="data data--req">
          <thead>
            <tr>
              <th>技能</th>
              <th>重要度</th>
              <th>证据强度</th>
              <th>编号</th>
              <th>{{ basisColumnLabel }}</th>
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

              <!-- 可追溯：编号来自证据数组位置，点击跳到对应原文 -->
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

              <td>
                <ul v-if="shownNotes(item).length" class="quote-list">
                  <li v-for="(note, i) in shownNotes(item)" :key="i">「{{ note }}」</li>
                </ul>
                <span v-if="notesOf(item).length > shownNotes(item).length" class="faint">
                  另有 {{ notesOf(item).length - shownNotes(item).length }} 句
                </span>
                <span v-if="!notesOf(item).length" class="faint">{{ noSourceHint }}</span>
              </td>

              <td class="muted">{{ item.reason || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="requirements.length" class="faint block-note">
        <template v-if="isUserJd">
          「招聘要求里没有这句话，是模型自己加的」表示这条<strong>不在你粘的原文里</strong>，
          是模型按常识补的 —— 可以不当真，也可以回去核对招聘页是否漏粘了一段。
        </template>
        <template v-else>
          这次没有粘贴招聘要求原文，上面每一条都是模型按行业常识推断的，
          <strong>没有原话可反查</strong>，因此也不给匹配度结论。
        </template>
      </p>
    </div>
  </section>
</template>
