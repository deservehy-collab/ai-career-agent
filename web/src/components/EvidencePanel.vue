<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import AgentTag from './AgentTag.vue'
import AppBadge from './AppBadge.vue'
import EvidenceRefChip from './EvidenceRefChip.vue'

import { buildReferencedBy, evidenceCode } from '../utils/evidence'
import { retrievalReasonText, retrievalStatusText, retrievalStatusTone } from '../utils/enums'

/**
 * 招聘要求原文面板：把「原话逐句 + 反向引用」合成一张卡。
 *
 * 硬约束
 * ------
 * 1. 每条原话的编号来自**数组位置**（见 utils/evidence.js），与后端 `evidence_ref()` 同规则。
 * 2. 没有原文时**如实空着**并说明原因，绝不拿模型推测冒充原话。
 * 3. 这里描述的是**岗位要什么**，不是**学生会什么**，副标题里明确写出来。
 */
const props = defineProps({
  /** job_evidence；null 表示结果里没有这个字段（与"空数组"不是一回事） */
  evidence: { type: Array, default: null },
  /** retrieval_status：user_pasted / no_source */
  status: { type: String, default: '' },
  /** retrieval_diagnostics：原话句数、被过滤的超长部分、空原文的原因 */
  diagnostics: { type: Object, default: null },
  /** job_requirements，用于计算"这条原话被哪些岗位要求引用"；不传则不显示该项 */
  requirements: { type: Array, default: null },
  /** 父组件要求高亮的编号（如从岗位要求表点过来的 E 编号） */
  activeRef: { type: String, default: '' },
})

const emit = defineEmits(['select'])

const items = computed(() => (Array.isArray(props.evidence) ? props.evidence : null))
const count = computed(() => (items.value ? items.value.length : 0))
const dropped = computed(() => props.diagnostics?.dropped_sentences ?? 0)
const reason = computed(() => retrievalReasonText(props.diagnostics?.reason))

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
        你提供的招聘要求原文
        <span class="sub">
          下面每一句都是从你粘贴的内容里切出来的原话 —— 描述「岗位要什么」，不是「学生会什么」
        </span>
      </h2>
      <div class="btn-row">
        <AppBadge
          v-if="status"
          :text="retrievalStatusText(status)"
          :tone="retrievalStatusTone(status)"
        />
        <AppBadge v-if="items !== null" :text="`${count} 句原话`" :tone="count ? 'primary' : 'warn'" />
        <AgentTag node="retrieval" />
      </div>
    </div>

    <div class="card-body">
      <!-- 字段缺失 ≠ 没有原文：这两种情况的措辞必须分开 -->
      <div v-if="items === null" class="empty">
        本次结果里没有岗位依据字段（后端未返回 job_evidence）。
      </div>

      <div v-else-if="!items.length" class="empty">
        {{ reason || '这次没有粘贴招聘要求原文' }} —— 岗位要求仍会生成，但全部是模型推测，没有原话佐证。
        <strong>想让它当真，把招聘页的「任职要求」粘到上面「把招聘要求粘到这里」那一栏。</strong>
      </div>

      <template v-else>
        <p v-if="dropped" class="notice notice-warn block-note">
          原文太长，超出 {{ items.length }} 句的部分没有参与分析（已丢弃 {{ dropped }} 句）。
        </p>
        <details class="fold" open>
          <summary>展开 {{ items.length }} 句原话</summary>
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
                <strong v-if="item.skill">{{ item.skill }}</strong>
              </header>

              <p class="evidence-quote">{{ item.note || '（本条没有原文）' }}</p>

              <div
                v-if="(requirements || []).length && referencedBy[evidenceCode(i)]?.length"
                class="evidence-meta"
              >
                <span class="evidence-refback">
                  被 {{ referencedBy[evidenceCode(i)].length }} 条岗位要求引用：
                  {{ referencedBy[evidenceCode(i)].join('、') }}
                </span>
              </div>
            </article>
          </div>
        </details>
      </template>
    </div>
  </section>
</template>
