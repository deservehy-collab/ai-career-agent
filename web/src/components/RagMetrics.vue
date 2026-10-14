<script setup>
import { computed } from 'vue'

import AppBadge from './AppBadge.vue'
import {
  matchKindText,
  matchKindTone,
  retrievalReasonText,
  retrievalStatusText,
  retrievalStatusTone,
} from '../utils/enums'

/**
 * RAG 检索指标条。**只渲染后端真的给了的指标。**
 *
 * 数据来源（都是真实字段，见 agents/retriever.py）：
 *   status                   → retrieval_status，取值 matched / not_mentioned / no_source / ambiguous
 *   evidence                 → job_evidence，条数即证据数
 *   diagnostics.match_kind   → exact_skill / overview / vector_only / term_scan
 *   diagnostics.sample_scope → {jd_count, companies[], caveat}
 *   diagnostics.note/caveat  → 后端自己写的口径说明，原样透出，不改写
 *
 * 任何一项缺失就**不渲染该项**，绝不用 0 或"—"占位 ——
 * "没给"和"是 0"是两件事。
 */
const props = defineProps({
  // ⚠️ 默认值必须是 null 而不是 []：
  // 传 [] 表示"后端确实返回了空证据列表"（证据条数 0，是事实）；
  // 不传（null）表示"调用方根本没给这一项"（我们对它一无所知）。
  // 若默认成 []，父组件漏传时界面会冒出"证据条数 0"——那是**编造的指标**。
  evidence: { type: Array, default: null },
  status: { type: String, default: '' },
  diagnostics: { type: Object, default: null },
})

const scope = computed(() => props.diagnostics?.sample_scope || null)

/** 只包含"确实有值"的指标项。 */
const metrics = computed(() => {
  const list = []

  if (props.status) {
    list.push({
      key: 'status',
      label: '检索状态',
      value: retrievalStatusText(props.status),
      tone: retrievalStatusTone(props.status),
    })
  }

  if (Array.isArray(props.evidence)) {
    list.push({ key: 'count', label: '证据条数', value: String(props.evidence.length), tone: null })
  }

  const kind = props.diagnostics?.match_kind
  if (kind) {
    list.push({
      key: 'kind',
      label: '命中路径',
      value: matchKindText(kind),
      tone: matchKindTone(kind),
    })
  }

  if (scope.value && typeof scope.value.jd_count === 'number') {
    list.push({ key: 'jd', label: '样本 JD', value: `${scope.value.jd_count} 份`, tone: null })
  }

  if (scope.value?.companies?.length) {
    list.push({
      key: 'companies',
      label: '覆盖公司',
      value: scope.value.companies.join('、'),
      tone: null,
    })
  }

  return list
})

const caveat = computed(() => scope.value?.caveat || '')
const note = computed(() => props.diagnostics?.note || '')
const reason = computed(() => retrievalReasonText(props.diagnostics?.reason))
const errors = computed(() => props.diagnostics?.errors || [])
</script>

<template>
  <div>
    <div v-if="metrics.length" class="metric-strip">
      <div v-for="item in metrics" :key="item.key" class="metric">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value">
          <AppBadge v-if="item.tone" :text="item.value" :tone="item.tone" />
          <template v-else>{{ item.value }}</template>
        </div>
      </div>
    </div>

    <div v-else class="notice notice-info" style="margin-bottom: 0">
      本次结果里没有检索诊断信息（后端未返回 retrieval_status 与 retrieval_diagnostics）。
    </div>

    <div v-if="reason" class="notice notice-info">
      <strong>检索说明：</strong>{{ reason }}
    </div>

    <div v-for="(err, i) in errors" :key="i" class="notice notice-warn">
      {{ err }}
    </div>

    <div v-if="note" class="notice notice-info">{{ note }}</div>

    <div v-if="caveat" class="notice notice-warn">{{ caveat }}</div>
  </div>
</template>
