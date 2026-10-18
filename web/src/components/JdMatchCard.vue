<script setup>
import { computed } from 'vue'

import AppBadge from './AppBadge.vue'
import { formatImportance, formatMatchRate, hasMatchRate } from '../utils/format'
import { jdOverallText, jdOverallTone, priorityTone } from '../utils/enums'

/**
 * 真实 JD 定向匹配结论（backend/services.py → graph/workflow.py build_final_plan → agents/jd_match.py）。
 * 真实字段：{jd_target, matched_jd_count, overall, requirement_total, requirement_judged,
 *   requirement_orphan, requirement_satisfied, requirement_shortfall, match_rate,
 *   hard_blocks[], key_gaps[], jd_source_warning}
 *
 * ⚠️ match_rate 为 null 表示"没有可判定要求"，必须显示成"无可判定要求"，
 * **不能显示成 0%** —— 那是把"判不了"说成"一个都不满足"。
 */
const props = defineProps({
  match: { type: Object, default: null },
})

const rateText = computed(() => formatMatchRate(props.match?.match_rate))
const rateAvailable = computed(() => hasMatchRate(props.match?.match_rate))
const warning = computed(() => props.match?.jd_source_warning || null)
const hardBlocks = computed(() => props.match?.hard_blocks || [])
const keyGaps = computed(() => props.match?.key_gaps || [])
</script>

<template>
  <section v-if="match" class="card">
    <div class="card-head">
      <h2>
        真实 JD 匹配
        <span class="sub">
          工作流结束后的确定性汇总（compute_jd_match，非 Agent 节点，因此不挂归属标记）
          · {{ match.jd_target ? `目标：${match.jd_target}` : '未指定具体 JD（跨公司概览）' }}
        </span>
      </h2>
      <AppBadge :text="jdOverallText(match.overall)" :tone="jdOverallTone(match.overall)" />
    </div>

    <div class="card-body">
      <!-- 统计合并成一本账：一张卡里再套三张同规格小卡，就是后台模板的指纹 -->
      <dl class="ledger">
        <div>
          <dt>满足率</dt>
          <dd :class="{ 'is-mono': rateAvailable }">{{ rateText }}</dd>
        </div>
        <div>
          <dt>有证据归属的要求</dt>
          <dd>{{ match.requirement_total }} 项</dd>
        </div>
        <div>
          <dt>可判定</dt>
          <dd>{{ match.requirement_judged }} 项</dd>
        </div>
        <div>
          <dt>已满足</dt>
          <dd>{{ match.requirement_satisfied }} 项</dd>
        </div>
        <div>
          <dt>存在差距</dt>
          <dd>{{ match.requirement_shortfall }} 项</dd>
        </div>
        <div>
          <dt>证据不足</dt>
          <dd>{{ match.requirement_orphan }} 项</dd>
        </div>
        <div>
          <dt>提供可用证据的 JD</dt>
          <dd>{{ match.matched_jd_count }} 份</dd>
        </div>
      </dl>

      <p class="faint block-note">
        {{ rateAvailable
          ? `满足率的分母 = 可判定要求 ${match.requirement_judged} 项。`
          : '本次没有可判定要求，因此不出满足率（不是 0%）。' }}
      </p>

      <div v-if="warning" class="notice notice-warn block-note">
        <strong>来源提示：</strong>{{ warning }}
      </div>

      <template v-if="hardBlocks.length">
        <h3 class="sub-title is-warn block-note">硬性缺口候选（{{ hardBlocks.length }} 项）</h3>
        <p class="faint">
          supported = 技能名与证据完全同名；partially_supported = 仅别名/语义相关，
          证据强度弱于前者，不等于完全确认。
        </p>
        <div class="tags">
          <span v-for="block in hardBlocks" :key="block.skill" class="badge badge-danger">
            {{ block.skill }}（要求 {{ block.required_level || '—' }}
            · {{ block.evidence_status || '未知' }}）
          </span>
        </div>
      </template>

      <template v-if="keyGaps.length">
        <h3 class="sub-title block-note">关键差距（按优先级）</h3>
        <div class="tags">
          <span v-for="gap in keyGaps" :key="gap.skill">
            <AppBadge
              :text="`${gap.skill} · ${gap.priority || '—'} · 重要度 ${formatImportance(gap.importance)}`"
              :tone="priorityTone(gap.priority)"
            />
          </span>
        </div>
      </template>
    </div>
  </section>
</template>
