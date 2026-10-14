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
      <div class="grid grid-3">
        <div class="card" style="margin: 0; box-shadow: none">
          <div class="card-body">
            <div class="faint">满足率</div>
            <div style="font-size: 26px; font-weight: 700" :class="{ faint: !rateAvailable }">
              {{ rateText }}
            </div>
            <div class="faint" v-if="rateAvailable">
              分母 = 可判定要求 {{ match.requirement_judged }} 项
            </div>
            <div class="faint" v-else>本次没有可判定要求，因此不出满足率</div>
          </div>
        </div>

        <div class="card" style="margin: 0; box-shadow: none">
          <div class="card-body">
            <div class="faint">岗位要求统计</div>
            <dl class="kv" style="margin-top: 8px; grid-template-columns: 96px 1fr">
              <dt>有证据归属</dt>
              <dd>{{ match.requirement_total }} 项</dd>
              <dt>可判定</dt>
              <dd>{{ match.requirement_judged }} 项</dd>
              <dt>已满足</dt>
              <dd>{{ match.requirement_satisfied }} 项</dd>
              <dt>存在差距</dt>
              <dd>{{ match.requirement_shortfall }} 项</dd>
              <dt>证据不足</dt>
              <dd>{{ match.requirement_orphan }} 项</dd>
            </dl>
          </div>
        </div>

        <div class="card" style="margin: 0; box-shadow: none">
          <div class="card-body">
            <div class="faint">参与匹配的 JD</div>
            <div style="font-size: 26px; font-weight: 700">{{ match.matched_jd_count }}</div>
            <div class="faint">份来源 JD 提供了可用证据</div>
          </div>
        </div>
      </div>

      <div v-if="warning" class="notice notice-warn" style="margin-top: 16px">
        <strong>来源提示：</strong>{{ warning }}
      </div>

      <div v-if="hardBlocks.length" style="margin-top: 16px">
        <h3 style="font-size: 13px">硬性缺口候选（{{ hardBlocks.length }} 项）</h3>
        <p class="faint" style="margin: 4px 0 8px">
          supported = 技能名与证据完全同名；partially_supported = 仅别名/语义相关，
          证据强度弱于前者，不等于完全确认。
        </p>
        <div class="tags">
          <span v-for="block in hardBlocks" :key="block.skill" class="badge badge-danger">
            {{ block.skill }}（要求 {{ block.required_level || '—' }}
            · {{ block.evidence_status || '未知' }}）
          </span>
        </div>
      </div>

      <div v-if="keyGaps.length" style="margin-top: 16px">
        <h3 style="font-size: 13px">关键差距（按优先级）</h3>
        <div class="tags" style="margin-top: 8px">
          <span v-for="gap in keyGaps" :key="gap.skill">
            <AppBadge
              :text="`${gap.skill} · ${gap.priority || '—'} · 重要度 ${formatImportance(gap.importance)}`"
              :tone="priorityTone(gap.priority)"
            />
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
