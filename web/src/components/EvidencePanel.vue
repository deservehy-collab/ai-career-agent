<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import AgentTag from './AgentTag.vue'
import AppBadge from './AppBadge.vue'
import EvidenceRefChip from './EvidenceRefChip.vue'
import RagMetrics from './RagMetrics.vue'

import { buildReferencedBy, evidenceCode } from '../utils/evidence'
import { evidenceOriginText, evidenceOriginTone, retrievalStatusText, retrievalStatusTone } from '../utils/enums'
import { formatImportance, joinList } from '../utils/format'

/**
 * RAG 证据面板：把「检索指标 + 真实岗位证据 + 来源信息 + 反向引用」合成一张卡。
 *
 * 硬约束
 * ------
 * 1. 每条证据的编号来自**数组位置**（见 utils/evidence.js），与后端 `evidence_ref()` 同规则。
 * 2. 每个字段**存在才渲染**：`companies` / `requirement_types` / `jd_count` / `also_supports`
 *    只在概览检索路径下才有（agents/retriever.py::_overview_evidence），
 *    精确/向量路径下它们根本不存在 —— 缺了就整行不显示，绝不用 0 或"—"占位。
 * 3. 证据描述的是**岗位要什么**，不是**学生会什么**，卡片副标题里明确写出来。
 */
const props = defineProps({
  /** job_evidence；null 表示结果里没有这个字段（与"空数组"不是一回事） */
  evidence: { type: Array, default: null },
  /** retrieval_status */
  status: { type: String, default: '' },
  /** retrieval_diagnostics */
  diagnostics: { type: Object, default: null },
  /** job_requirements，用于计算"这条证据被哪些岗位要求引用"；不传则不显示该项 */
  requirements: { type: Array, default: null },
  /** 父组件要求高亮的编号（如从岗位要求表点过来的 E 编号） */
  activeRef: { type: String, default: '' },
})

const emit = defineEmits(['select'])

const items = computed(() => (Array.isArray(props.evidence) ? props.evidence : null))
const count = computed(() => (items.value ? items.value.length : 0))

// 反向引用：编号 → 引用了它的岗位要求技能名
const referencedBy = computed(() => buildReferencedBy(props.requirements || [], items.value || []))

/** 本地闪光态：3 秒后自动收起，这样重复点击同一个编号能再次触发动画。 */
const flash = ref('')
let timer = null

const itemEls = new Map()
function setItemEl(code) {
  return (el) => {
    if (el) itemEls.set(code, el)
    else itemEls.delete(code)
  }
}

function refsFor(code) {
  return referencedBy.value[code] || []
}

/** 只有向量路径才带真实距离；其余路径 distance 为 null，不显示。 */
function distanceText(item) {
  return typeof item?.distance === 'number' ? item.distance.toFixed(4) : ''
}

watch(
  () => props.activeRef,
  (code) => {
    if (!code) return
    flash.value = code
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      flash.value = ''
      timer = null
    }, 3000)

    const el = itemEls.get(code)
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <section id="card-evidence" class="card">
    <div class="card-head">
      <h2>
        RAG 检索证据
        <span class="sub">岗位知识库里的 JD 原文出处 —— 描述「岗位要什么」，不是「学生会什么」</span>
      </h2>
      <div class="btn-row">
        <AppBadge
          v-if="status"
          :text="retrievalStatusText(status)"
          :tone="retrievalStatusTone(status)"
        />
        <AppBadge
          v-if="items !== null"
          :text="`${count} 条证据`"
          :tone="count ? 'primary' : 'warn'"
        />
        <AgentTag node="retrieval" />
      </div>
    </div>

    <div class="card-body">
      <RagMetrics :evidence="evidence" :status="status" :diagnostics="diagnostics" />

      <!-- 字段缺失 ≠ 证据为空：这两种情况的措辞必须分开 -->
      <div v-if="items === null" class="empty">
        本次结果里没有岗位证据字段（后端未返回 job_evidence）。
      </div>

      <div v-else-if="!items.length" class="empty">
        没有可用证据，已降级继续 —— 岗位要求仍由 Job Agent 生成，只是缺少 JD 原文佐证。
      </div>

      <details v-else class="fold" open>
        <summary>展开 {{ items.length }} 条证据</summary>
        <div class="fold-body">
          <article
            v-for="(item, i) in items"
            :key="evidenceCode(i)"
            :ref="setItemEl(evidenceCode(i))"
            class="evidence-item"
            :class="{ 'is-flashing': flash === evidenceCode(i) }"
          >
            <header class="evidence-head">
              <EvidenceRefChip
                :code="evidenceCode(i)"
                :active="flash === evidenceCode(i)"
                @select="emit('select', $event)"
              />
              <strong>{{ item.skill || '未标注技能' }}</strong>
              <span class="muted">{{ item.company_slug || '未标注公司' }}</span>
              <AppBadge v-if="item.requirement_type" :text="item.requirement_type" />
              <AppBadge
                v-if="item.origin"
                :text="evidenceOriginText(item.origin)"
                :tone="evidenceOriginTone(item.origin)"
              />
              <span class="faint">重要度 {{ formatImportance(item.importance) }}</span>
            </header>

            <p class="evidence-quote">{{ item.note || '（本条没有证据原文）' }}</p>

            <p v-if="item.context" class="faint evidence-ctx">
              原文出处：{{ item.context }}
            </p>

            <div class="evidence-meta">
              <span v-if="item.companies?.length">覆盖公司：{{ joinList(item.companies) }}</span>
              <span v-if="item.requirement_types?.length">
                要求类型：{{ joinList(item.requirement_types) }}
              </span>
              <span v-if="typeof item.jd_count === 'number'">样本：{{ item.jd_count }} 份 JD</span>
              <span v-if="distanceText(item)">向量距离：{{ distanceText(item) }}</span>
              <span v-if="item.also_supports?.length">
                同时支撑：{{ joinList(item.also_supports) }}
              </span>
              <span v-if="refsFor(evidenceCode(i)).length" class="evidence-refback">
                被 {{ refsFor(evidenceCode(i)).length }} 条岗位要求引用：{{ joinList(refsFor(evidenceCode(i))) }}
              </span>
              <span v-if="item.source_id" class="mono">source_id: {{ item.source_id }}</span>
            </div>
          </article>
        </div>
      </details>
    </div>
  </section>
</template>
