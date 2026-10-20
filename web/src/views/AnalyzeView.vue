<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

import AgentPipeline from '../components/AgentPipeline.vue'
import AgentTag from '../components/AgentTag.vue'
import AppBadge from '../components/AppBadge.vue'
import EvidencePanel from '../components/EvidencePanel.vue'
import JdMatchCard from '../components/JdMatchCard.vue'
import JobRequirementTable from '../components/JobRequirementTable.vue'
import LearningPlanList from '../components/LearningPlanList.vue'
import ProfileForm from '../components/ProfileForm.vue'
import ProjectPlanList from '../components/ProjectPlanList.vue'
import RunProgressCard from '../components/RunProgressCard.vue'
import SkillGapTable from '../components/SkillGapTable.vue'
import SkillTable from '../components/SkillTable.vue'

import { useAnalysisStore } from '../stores/analysis'
import { JD_TEXT_LIMIT, useProfileStore } from '../stores/profile'
import { summarizeWorkflow } from '../utils/agents'
import {
  growthOutcomeText,
  growthOutcomeTone,
  levelTone,
  requirementBasisText,
} from '../utils/enums'
import { joinList } from '../utils/format'

const profile = useProfileStore()
const analysis = useAnalysisStore()

/** 招聘要求原文：存在 profile store 里，跟着 localStorage 一起留住，下次不用重粘。 */
const jdText = computed({
  get: () => profile.jdText,
  set: (value) => {
    profile.jdText = value
  },
})

onBeforeUnmount(() => analysis.cancel())

const targetLabel = computed(() =>
  profile.hasJdText ? '你粘贴的招聘要求' : '没粘原文（模型推断）',
)

/** 前端把能提前拦下的都拦掉，避免打到后端才报 422。 */
const blockingReason = computed(() => {
  if (!profile.canAnalyze) return '请先填写「目标岗位」——后端要求非空。'
  if (profile.jdTextOverflow) return '粘贴的原文超过 6000 字，请精简后再分析（太长模型也读不完）。'
  return ''
})

const result = computed(() => analysis.result)
const finalPlan = computed(() => analysis.finalPlan)
const requirementBasis = computed(() => analysis.requirementBasis)

/** 依据横幅的色调 → notice 样式类（两档都有对应类，不做默认兜底）。 */
const basisNoticeClass = computed(
  () =>
    ({
      user_pasted: 'notice notice-ok',
      model_only: 'notice notice-danger',
    })[requirementBasis.value] || 'notice',
)

/** 横幅里那句"这算什么依据"的补充说明。 */
const basisNote = computed(() => {
  if (requirementBasis.value === 'user_pasted') {
    return '岗位要求只从你粘贴的原话里得出，每条都能点开对照到具体句子。'
  }
  return '这次没有粘贴招聘要求原文，下面的岗位要求是模型凭自身常识给的 —— 只能当思路参考，别当门槛结论。'
})


/** 一旦开始跑或已有结果，就切到两栏工作区。 */
const showWorkspace = computed(() => analysis.status !== 'idle' || !!result.value)

/**
 * 各节点的真实产出摘要（utils/agents.js）。
 * 没有结果时返回 null —— 流程轨据此保持中性格，不显示任何产出，也不标任何节点状态。
 */
const workflowSummary = computed(() => summarizeWorkflow(result.value))

/** 结论摘要的账本行：只填后端真给出来的字段，缺了就整行不出现。 */
const summaryRows = computed(() => {
  const plan = finalPlan.value
  if (!plan) return []
  const rows = []
  const job = plan.target_job || analysis.targetJob
  if (job) rows.push({ key: 'job', label: '目标岗位', value: job })
  if (typeof plan.learning_stage_count === 'number') {
    rows.push({ key: 'stages', label: '学习阶段', value: `${plan.learning_stage_count} 个` })
  }
  rows.push({
    key: 'projects',
    label: '推荐项目',
    value: `${plan.recommended_projects?.length ?? 0} 个`,
  })
  return rows
})

// ── 成长节点（agents/growth_agent.py 的 growth_diff）────────────────────
const growthDiff = computed(() => result.value?.growth_diff || null)
const levelChanges = computed(() => growthDiff.value?.level_changes || [])
const blockedUpgrades = computed(() => growthDiff.value?.blocked_upgrades || [])
const growthWarnings = computed(() => growthDiff.value?.warnings || [])
const baselineSkills = computed(() => result.value?.user_skills_before || [])

// ── 证据编号 → 证据面板定位 ────────────────────────────────────────────
const activeEvidenceRef = ref('')

function handleSelectRef(code) {
  if (!code) return
  if (activeEvidenceRef.value === code) {
    // 再点同一个编号：先清空再置回，让面板的高亮动画能重新触发
    activeEvidenceRef.value = ''
    nextTick(() => {
      activeEvidenceRef.value = code
    })
    return
  }
  activeEvidenceRef.value = code
}

function handleStart() {
  if (blockingReason.value || analysis.isRunning) return

  activeEvidenceRef.value = ''
  analysis.start({
    profile: profile.toRequestProfile(),
    targetJob: profile.targetJob.trim(),
    jdText: jdText.value,
  })
}

function handleReset() {
  activeEvidenceRef.value = ''
  analysis.reset()
}
</script>

<template>
  <div>
    <div class="page-head">
      <h1>岗位分析</h1>
      <p>
        把你的<strong>目标岗位</strong>和一份<strong>招聘要求原文</strong>交给系统，
        由 7 个专职 Agent 顺序协作：能力画像 → 成长追踪 → 岗位依据整理 → 岗位要求 → 能力差距 → 学习路线 → 实战项目。
      </p>
      <p class="faint">
        最省事的做法：在招聘 App 上看到心仪岗位，把「任职要求」整段复制粘贴到下面，任何专业、任何岗位都能分析。
      </p>
    </div>

    <!-- 输入区：画像 + 招聘要求原文同处一块沉底表面，白底控件浮在上面 -->
    <section class="panel">
      <ProfileForm />

      <section class="panel-block">
        <div class="panel-head">
          <h2>分析目标</h2>
          <span class="badge badge-primary">{{ targetLabel }}</span>
        </div>

        <div class="field">
          <label for="an-jd-text">
            把招聘要求粘到这里
            <span class="hint">去招聘页把「任职要求」整段复制过来就行，不用整理</span>
          </label>
          <textarea
            id="an-jd-text"
            v-model="jdText"
            rows="7"
            placeholder="例：&#10;1、本科及以上学历，新闻学、汉语言文学相关专业优先&#10;2、具备扎实的文案撰写能力，能独立完成公众号推文&#10;3、熟练使用 PS、剪映等图文与视频工具"
          />
          <div class="btn-row btn-row--tight">
            <span class="faint field-count">{{ profile.jdTextLength }} / {{ JD_TEXT_LIMIT }} 字</span>
            <button v-if="profile.hasJdText" class="btn btn-sm" @click="jdText = ''">
              清空原文
            </button>
          </div>
          <p class="faint block-note">
            这里粘的是<strong>招聘方对这个岗位的要求</strong>，不是你自己的简历。
            粘了之后，本次岗位要求完全以这些原话为准，每条都能反查到你粘的哪一句；
            <strong>不粘就没有任何原文依据</strong>，岗位要求全由模型推断，下面会整栏标灰并说明。
          </p>
        </div>

        <div v-if="blockingReason" class="notice notice-warn">{{ blockingReason }}</div>

        <div class="btn-row form-actions">
          <button
            class="btn btn-primary"
            :disabled="!!blockingReason || analysis.isRunning"
            @click="handleStart"
          >
            <span v-if="analysis.isRunning" class="spinner" />
            {{ analysis.isRunning ? '分析中…' : '开始分析' }}
          </button>
          <button v-if="analysis.hasResult || analysis.errorMessage" class="btn" @click="handleReset">
            清空结果
          </button>
          <span class="faint">
            分析不写成长历史；只有第一次分析会把给出的学习与项目任务存成第 1 轮清单。
          </span>
        </div>
      </section>
    </section>

    <!-- 两栏工作区：左流程轨 + 右结果 -->
    <div v-if="showWorkspace" class="layout-rail">
      <AgentPipeline :summary="workflowSummary" :status="analysis.status" />

      <div>
        <RunProgressCard
          :status="analysis.status"
          :started-at="analysis.startedAt"
          :finished-at="analysis.finishedAt"
          :error-message="analysis.errorMessage"
          :error-kind="analysis.errorKind"
          title="分析进度"
        />

        <!--
          结果还没回来时的占位。后端只提供排队/运行中/成功/失败四态，**没有进度百分比**，
          所以这里只有灰条和一句说明：不画假进度，也不给任何单个节点标状态。
        -->
        <template v-if="analysis.isRunning && !result">
          <p class="faint sk-note">
            七个节点跑完后，结论摘要、能力画像、岗位要求与差距、学习路线会依次出现在下面。
          </p>
          <div class="sk-stack" aria-hidden="true">
            <div v-for="block in 3" :key="block" class="card sk-card">
              <div class="sk-bar sk-title" />
              <div class="sk-bar sk-line" />
              <div class="sk-bar sk-line" />
              <div class="sk-bar sk-line" />
              <div class="sk-bar sk-line" />
            </div>
          </div>
        </template>

        <template v-if="result">
          <!-- 本次岗位要求的依据来源：两档，决定下面几栏能不能当真 -->
          <div :class="basisNoticeClass" class="notice--tight">
            <strong>{{ requirementBasisText(requirementBasis) }}</strong>
            <p class="notice-body">{{ basisNote }}</p>
          </div>

          <!-- 汇总：final_plan 由图后的确定性汇总得出，不属于任一 Agent 节点 -->
          <section class="panel">
            <div class="panel-head">
              <h2>结论摘要</h2>
              <span class="panel-src">由七个步骤的结果汇总得出</span>
            </div>

            <dl v-if="summaryRows.length" class="ledger">
              <div v-for="row in summaryRows" :key="row.key">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>

            <div v-if="finalPlan?.next_action" class="notice notice-info block-note">
              <strong>下一步：</strong>{{ finalPlan.next_action }}
            </div>

            <div class="grid grid-2 form-actions">
              <div>
                <h3 class="sub-title is-warn">最需要补的缺口</h3>
                <div class="tags">
                  <span v-for="gap in finalPlan?.top_gaps || []" :key="gap" class="badge badge-danger">
                    {{ gap }}
                  </span>
                  <span v-if="!(finalPlan?.top_gaps || []).length" class="faint">没有高优先级缺口</span>
                </div>
              </div>
              <div>
                <h3 class="sub-title is-ok">已满足的岗位要求</h3>
                <div class="tags">
                  <span v-for="skill in finalPlan?.already_satisfied || []" :key="skill" class="badge badge-ok">
                    {{ skill }}
                  </span>
                  <span v-if="!(finalPlan?.already_satisfied || []).length" class="faint">暂无</span>
                </div>
              </div>
            </div>
          </section>

          <JdMatchCard :match="analysis.jdMatch" :basis="requirementBasis" />

          <div id="card-profile">
            <SkillTable
              :skills="result.user_skills || []"
              :strengths="result.user_strengths || []"
              :weaknesses="result.user_weaknesses || []"
              agent-node="profile"
            />
          </div>

          <!-- 成长追踪：growth_node 的产出（含能力基线），本轮无事件时如实说明 -->
          <div id="card-growth">
            <section class="card">
              <div class="card-head">
                <h2>
                  成长追踪
                  <span class="sub">合并成长历史后的能力基线，以及本轮成长事件带来的等级变化</span>
                </h2>
                <div class="btn-row">
                  <AppBadge
                    v-if="growthDiff?.outcome"
                    :text="growthOutcomeText(growthDiff.outcome)"
                    :tone="growthOutcomeTone(growthDiff.outcome)"
                  />
                  <AgentTag node="growth" />
                </div>
              </div>
              <div class="card-body">
                <div v-if="!growthDiff" class="empty">本次结果里没有成长追踪字段（growth_diff）。</div>
                <template v-else>
                  <div class="metric-strip">
                    <div class="metric">
                      <div class="metric-label">收到成长事件</div>
                      <div class="metric-value">{{ growthDiff.events_received ?? 0 }} 条</div>
                    </div>
                    <div class="metric">
                      <div class="metric-label">等级变化</div>
                      <div class="metric-value">{{ levelChanges.length }} 项</div>
                    </div>
                    <div class="metric">
                      <div class="metric-label">被前置门禁拦下</div>
                      <div class="metric-value">{{ blockedUpgrades.length }} 项</div>
                    </div>
                    <div class="metric">
                      <div class="metric-label">能力基线条目</div>
                      <div class="metric-value">{{ baselineSkills.length }} 项</div>
                    </div>
                  </div>

                  <template v-if="baselineSkills.length">
                    <h3 class="sub-title block-note">合并历史后的能力基线</h3>
                    <div class="tags">
                      <span v-for="item in baselineSkills" :key="item.skill">
                        <AppBadge
                          :text="`${item.skill} · ${item.level || '无'}`"
                          :tone="levelTone(item.level)"
                        />
                      </span>
                    </div>
                  </template>

                  <template v-if="levelChanges.length">
                    <h3 class="sub-title block-note">技能等级变化</h3>
                    <ul class="plain-list muted">
                      <li v-for="item in levelChanges" :key="item.skill">
                        {{ item.skill }}：{{ item.from || '无' }} → {{ item.to }}
                        <span class="faint">（来源成果：{{ item.source }}）</span>
                      </li>
                    </ul>
                  </template>

                  <template v-if="blockedUpgrades.length">
                    <h3 class="sub-title block-note">被前置门禁拦下的升级</h3>
                    <ul class="plain-list muted">
                      <li v-for="item in blockedUpgrades" :key="item.skill">
                        {{ item.skill }}（缺前置：{{ joinList(item.missing_prerequisites, '未给出') }}）
                      </li>
                    </ul>
                  </template>

                  <div v-for="(warn, i) in growthWarnings" :key="i" class="notice notice-warn block-note">
                    {{ warn }}
                  </div>

                  <p class="faint block-note">
                    本页分析是<strong>只读</strong>的：不会写入成长历史。
                    正式记一次成长，是在「成长记录」页点「生成下一轮」的时候。
                  </p>
                </template>
              </div>
            </section>
          </div>

          <!-- 依据面板：EvidencePanel 自带 id="card-evidence" -->
          <EvidencePanel
            :evidence="result.job_evidence ?? null"
            :status="result.retrieval_status || ''"
            :diagnostics="result.retrieval_diagnostics ?? null"
            :requirements="result.job_requirements ?? null"
            :active-ref="activeEvidenceRef"
            @select="handleSelectRef"
          />

          <div id="card-requirements">
            <JobRequirementTable
              :requirements="result.job_requirements || []"
              agent-node="job"
              :active-ref="activeEvidenceRef"
              :basis="requirementBasis"
              @select-ref="handleSelectRef"
            />
          </div>

          <div id="card-gaps">
            <SkillGapTable :gaps="result.skill_gaps || []" agent-node="assessment" />
          </div>

          <div id="card-learning">
            <LearningPlanList :stages="result.learning_plan || []" agent-node="learning" />
          </div>

          <div id="card-projects">
            <ProjectPlanList :projects="result.project_plan || []" agent-node="project" />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
