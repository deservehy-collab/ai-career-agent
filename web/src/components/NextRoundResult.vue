<script setup>
import { computed } from 'vue'

import AppBadge from './AppBadge.vue'
import { growthOutcomeText, growthOutcomeTone } from '../utils/enums'

/**
 * 「生成下一轮」的结果面板。
 *
 * `POST /api/growth/next-round` 的 result 有两种形状（backend/services.py::_run_next_round）：
 *   完整分支 —— 有待处理成果时走这条，带 round_created / history_written / growth_upgraded 等
 *   早退分支 —— 没有待处理成果时直接返回，**只有** ok/round_created/history_written/growth_outcome 等，
 *               target_job、user_skills、growth_diff、learning_plan 等字段**根本不存在**
 *
 * 三件事必须分开显示，**任何一项成功都不等于全部成功**：
 *   round_created  —— 新轮次是否写进 runs/loop.json
 *   history_written—— 成长历史是否写进 runs/growth.json
 *   growth_upgraded—— 本次是否真的升级了技能等级
 * 三者可以任意组合，"成长写了但轮次没存"是合法的部分成功，由 warning 如实说明。
 */
const props = defineProps({
  result: { type: Object, required: true },
})

const r = computed(() => props.result || {})

/** 早退分支没有这些字段 —— 据此判断"本次根本没跑流水线"。 */
const isShortCircuit = computed(
  () => r.value.target_job === undefined && r.value.learning_plan === undefined,
)
</script>

<template>
  <div>
    <h3 class="mini-title">本次生成结果</h3>

    <!-- 三个独立状态，互不替代 -->
    <div class="metric-strip result-note">
      <div class="metric">
        <div class="metric-label">新任务清单</div>
        <div class="metric-value">
          <AppBadge
            :text="r.round_created ? `第 ${r.round_no} 轮已创建` : '未创建'"
            :tone="r.round_created ? 'ok' : 'muted'"
          />
        </div>
      </div>
      <div class="metric">
        <div class="metric-label">成长历史</div>
        <div class="metric-value">
          <AppBadge
            :text="r.history_written ? '已写入' : '未写入'"
            :tone="r.history_written ? 'ok' : 'muted'"
          />
        </div>
      </div>
      <div class="metric">
        <div class="metric-label">技能升级</div>
        <div class="metric-value">
          <AppBadge
            :text="r.growth_upgraded ? '有等级提升' : '无等级提升'"
            :tone="r.growth_upgraded ? 'ok' : 'muted'"
          />
        </div>
      </div>
      <div class="metric">
        <div class="metric-label">交接成果</div>
        <div class="metric-value">{{ r.events_handed_over ?? 0 }} 条</div>
      </div>
    </div>

    <dl class="kv kv--mid sub-block">
      <dt>成长结论</dt>
      <dd>
        <AppBadge
          :text="growthOutcomeText(r.growth_outcome)"
          :tone="growthOutcomeTone(r.growth_outcome)"
        />
      </dd>
      <template v-if="r.target_job">
        <dt>目标岗位</dt>
        <dd>{{ r.target_job }}</dd>
      </template>
      <template v-if="r.user_skills">
        <dt>本轮能力表</dt>
        <dd>{{ r.user_skills.length }} 项</dd>
      </template>
    </dl>

    <div v-if="r.warning" class="notice notice-warn sub-block">{{ r.warning }}</div>
    <div v-for="(warn, i) in r.warnings || []" :key="i" class="notice notice-warn">{{ warn }}</div>

    <div v-if="isShortCircuit" class="notice notice-info sub-block flush-last">
      本次没有待处理成果，后端直接返回，<strong>未重跑流水线</strong>，因此没有新的学习 / 项目计划。
    </div>
    <p v-else class="faint flush-last">
      三项互相独立：轮次建了但成长没写、或成长写了但轮次没存，都是可能出现的<strong>部分成功</strong>，
      上方的提示会如实说明。
    </p>
  </div>
</template>
