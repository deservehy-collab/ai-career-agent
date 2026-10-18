<script setup>
import { computed } from 'vue'

import AgentTag from './AgentTag.vue'
import AppBadge from './AppBadge.vue'

import {
  baselineSourceText,
  baselineSourceTone,
  completionStatusText,
  completionStatusTone,
  eventStatusText,
  eventStatusTone,
  gateStatusText,
  gateStatusTone,
  growthOutcomeText,
  growthOutcomeTone,
  knowledgeBaseStatusText,
  knowledgeBaseStatusTone,
  loopStatusText,
  loopStatusTone,
} from '../utils/enums'
import { formatDateTime, joinList } from '../utils/format'

/**
 * 「提交任务完成」的结果面板。
 *
 * 后端 `POST /api/tasks/{id}/complete` 的返回体里塞了**三件性质完全不同的事**
 * （见 agents/growth_loop.py 的模块说明），必须分开呈现，绝不能让用户看见
 * "任务已完成"就以为"技能已经升上去了"：
 *
 *   ① 任务完成记录 —— 唯一真正落盘的一步（写 runs/loop.json）
 *   ② 成长成果     —— 这条任务能否构造成长事件（可能构不成）
 *   ③ 技能升级     —— **只是预览**，本接口不写 runs/growth.json；
 *                     正式落盘发生在「成长记录」页的「生成下一轮」时由 growth_node 完成
 */
const props = defineProps({
  /** complete 接口的原始返回体 */
  result: { type: Object, required: true },
})

const r = computed(() => props.result || {})
const updates = computed(() => r.value.updates || [])
const blocked = computed(() => r.value.blocked || [])
const skipped = computed(() => r.value.skipped || [])
const invalidEvents = computed(() => r.value.invalid_events || [])
const duplicateEvents = computed(() => r.value.duplicate_events || [])
const unmappedSkills = computed(() => r.value.unmapped_skills || [])
const warnings = computed(() => r.value.warnings || [])

const hasEvent = computed(() => !!r.value.growth_event)
/** 本次是否真的算出了升级计划（注意：是"计划"，不是"已升级"）。 */
const hasPreview = computed(() => r.value.growth_evaluated === true && updates.value.length > 0)

const isHistoryOnly = computed(() => r.value.baseline_source === 'history_only')
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h2>
        提交结果
        <span class="sub mono">{{ r.task_id }}</span>
      </h2>
      <div class="btn-row">
        <AppBadge :text="loopStatusText(r.status)" :tone="loopStatusTone(r.status)" />
        <AgentTag node="growth" />
      </div>
    </div>

    <div class="card-body">
      <!-- ① 任务完成记录 —— 唯一真正落盘的一步 -->
      <div class="result-block">
        <h3 class="result-title">
          ① 任务完成记录
          <span class="sub">写入 runs/loop.json，这是唯一真正落盘的一步</span>
        </h3>
        <div class="btn-row btn-row--tight">
          <AppBadge
            :text="completionStatusText(r.completion_status)"
            :tone="completionStatusTone(r.completion_status)"
          />
          <span class="faint">磁盘写入：{{ r.completion_written ? '是' : '否' }}</span>
        </div>
        <dl class="kv kv--mid">
          <dt>完成时间</dt>
          <dd>{{ formatDateTime(r.task?.completed_at) }}</dd>
          <dt>提交证据</dt>
          <dd>{{ r.task?.evidence || '（空）' }}</dd>
        </dl>
        <p v-if="r.already_completed" class="faint result-note">
          该任务此前已完成，本次<strong>未改动磁盘</strong>，第一次提交的证据不会被覆盖。
        </p>
        <p v-if="!r.completion_written && !r.already_completed" class="faint result-note">
          完成记录<strong>没有写入</strong>：{{ r.reason || '原因未给出' }}。
        </p>
      </div>

      <!-- ② 成长成果 -->
      <div class="result-block">
        <h3 class="result-title">
          ② 成长成果
          <span class="sub">这条任务能否构造成一个成长事件</span>
        </h3>
        <div class="btn-row btn-row--tight">
          <AppBadge
            :text="eventStatusText(r.growth_event_status)"
            :tone="eventStatusTone(r.growth_event_status)"
          />
        </div>

        <template v-if="hasEvent">
          <dl class="kv kv--mid">
            <dt>成果类型</dt>
            <dd>{{ r.growth_event.type === 'project' ? '项目成果' : '学习成果' }}</dd>
            <dt>成果标题</dt>
            <dd>{{ r.growth_event.title }}</dd>
            <dt>涉及技能</dt>
            <dd>{{ joinList(r.growth_event.skills, '（未关联技能）') }}</dd>
            <dt>证据原文</dt>
            <dd>{{ r.growth_event.evidence }}</dd>
          </dl>
        </template>
        <p v-else class="faint flush-first">
          没有构造成长成果：{{ r.reason || '原因未给出' }}。
          <strong>任务完成记录不受影响</strong>，只是这条任务无法作为技能升级的依据。
        </p>

        <div v-if="unmappedSkills.length" class="notice notice-warn">
          未识别的技能名（不会自动映射到相似技能）：{{ joinList(unmappedSkills) }}
        </div>
        <div v-if="duplicateEvents.length" class="notice notice-info">
          该成果历史上已处理过（指纹
          <span class="mono">{{ duplicateEvents[0].fingerprint }}</span>），跳过以免重复升级。
        </div>
        <div v-for="(item, i) in invalidEvents" :key="i" class="notice notice-warn">
          成果未通过校验：{{ item.reason }}
        </div>
      </div>

      <!-- ③ 技能升级预览 -->
      <div class="result-block flush-last">
        <h3 class="result-title">
          ③ 技能升级预览
          <span class="sub">只是预览，不是已升级</span>
        </h3>

        <div class="notice notice-warn notice--tight">
          <strong>预览尚未写入成长历史。</strong>
          本接口不会改动 <span class="mono">runs/growth.json</span>；
          技能等级正式落盘发生在「成长记录」页点击「生成下一轮」时，由 growth_node 完成。
        </div>

        <template v-if="!r.growth_evaluated">
          <div class="btn-row">
            <AppBadge
              :text="growthOutcomeText(r.growth_outcome) || '本次没有评估升级'"
              :tone="growthOutcomeTone(r.growth_outcome)"
            />
          </div>
          <p class="faint result-note">{{ r.reason || '' }}</p>
        </template>

        <template v-else>
          <div class="btn-row">
            <AppBadge
              :text="growthOutcomeText(r.growth_outcome)"
              :tone="growthOutcomeTone(r.growth_outcome)"
            />
            <span v-if="r.knowledge_base_status" class="faint">
              技能知识库：{{ knowledgeBaseStatusText(r.knowledge_base_status) }}
            </span>
          </div>

          <div v-if="hasPreview" class="sub-block">
            <h4 class="mini-title">预计等级变化（{{ updates.length }} 项）</h4>
            <ul class="muted mini-list">
              <li v-for="item in updates" :key="item.skill">
                <strong>{{ item.skill }}</strong>：{{ item.from || '无' }} → {{ item.to }}
                <span class="faint">
                  （前置门禁：{{ gateStatusText(item.gate_status) }}
                  <template v-if="item.gate_unavailable"> ⚠ 未经过校验</template>）
                </span>
              </li>
            </ul>
          </div>
          <p v-else class="faint result-note">本次没有产生任何等级提升。</p>

          <div v-if="blocked.length" class="sub-block">
            <h4 class="mini-title">被前置门禁拦下（{{ blocked.length }} 项）</h4>
            <ul class="muted mini-list">
              <li v-for="item in blocked" :key="item.skill">
                {{ item.skill }}：{{ item.current_level || '无' }} → 本可升到 {{ item.candidate_level }}
                <span class="faint">
                  （{{ gateStatusText(item.gate_status) }}
                  · 缺前置：{{ joinList(item.missing_prerequisites, '未给出') }}）
                </span>
                <span v-if="item.gate_unavailable" class="faint">
                  ⚠ 该技能因知识库不可用而未经过前置校验，不能当成"已通过门禁"
                </span>
              </li>
            </ul>
          </div>

          <div v-if="skipped.length" class="sub-block">
            <h4 class="mini-title">未升级的候选（{{ skipped.length }} 项）</h4>
            <ul class="muted mini-list">
              <li v-for="item in skipped" :key="item.skill">{{ item.skill }}：{{ item.reason }}</li>
            </ul>
          </div>

          <!-- 基线提示（措辞按约束：只说明更严格，不承诺结果一定更好） -->
          <div v-if="isHistoryOnly" class="notice notice-warn sub-block flush-last">
            <AppBadge
              :text="baselineSourceText(r.baseline_source)"
              :tone="baselineSourceTone(r.baseline_source)"
            />
            本次预览仅依据成长历史，可能比结合完整画像的评估更严格。
            在「岗位分析」页完成一次分析后，再提交任务即可让预览与正式判定使用同一基线。
          </div>
        </template>
      </div>

      <div v-for="(warn, i) in warnings" :key="i" class="notice notice-warn">{{ warn }}</div>
    </div>
  </section>
</template>
