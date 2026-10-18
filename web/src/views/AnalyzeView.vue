<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

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

import { listJds } from '../api/endpoints'
import { useAnalysisStore } from '../stores/analysis'
import { useProfileStore } from '../stores/profile'
import { summarizeWorkflow } from '../utils/agents'
import { growthOutcomeText, growthOutcomeTone, levelTone } from '../utils/enums'
import { joinList } from '../utils/format'

// ── 分析目标 ──────────────────────────────────────────────────────────
// 三种模式对应后端 AnalyzeRequest 的三种可选传参：
//   overview → 都不传（阶段二以来的默认跨公司概览）
//   company  → 传 target_company（公司级匹配）
//   jd       → 传 jd_source_id（精确匹配某份真实 JD，优先级最高）
const TARGET_MODES = [
  { value: 'overview', label: '跨公司概览', hint: '不限定公司，按整个岗位知识库检索' },
  { value: 'company', label: '指定公司', hint: '只检索该公司的 JD 证据' },
  { value: 'jd', label: '指定真实 JD', hint: '精确匹配某一份 JD，匹配结论最具体' },
]

const profile = useProfileStore()
const analysis = useAnalysisStore()

const mode = ref('overview')
const companySlug = ref('')
const jdSourceId = ref('')

const jds = ref([])
const jdsError = ref('')
const jdsLoading = ref(false)

onMounted(async () => {
  jdsLoading.value = true
  try {
    const payload = await listJds()
    jds.value = Array.isArray(payload?.jds) ? payload.jds : []
  } catch (error) {
    jdsError.value = error?.message || '加载 JD 列表失败'
  } finally {
    jdsLoading.value = false
  }
})

onBeforeUnmount(() => analysis.cancel())

/** JD 下拉的来源；按公司分组展示更易读。 */
const jdOptions = computed(() =>
  jds.value.map((jd) => ({
    value: jd.source_id,
    label: `${jd.company || jd.company_slug} · ${jd.job_name || jd.source_id}`,
    jd,
  })),
)

/** 公司下拉来自 JD 列表里去重后的公司 —— 保证传过去的公司名后端一定能解析。 */
const companyOptions = computed(() => {
  const seen = new Map()
  for (const jd of jds.value) {
    const slug = jd.company_slug
    if (slug && !seen.has(slug)) seen.set(slug, jd.company || slug)
  }
  return [...seen.entries()].map(([value, label]) => ({ value, label }))
})

const selectedJd = computed(() => jds.value.find((jd) => jd.source_id === jdSourceId.value) || null)

const targetLabel = computed(() => {
  if (mode.value === 'jd') return selectedJd.value ? `JD ${selectedJd.value.source_id}` : '未选择 JD'
  if (mode.value === 'company') return companySlug.value ? `公司 ${companySlug.value}` : '未选择公司'
  return '跨公司概览'
})

const modeHint = computed(
  () => TARGET_MODES.find((item) => item.value === mode.value)?.hint || '',
)

/** 前端把能提前拦下的都拦掉，避免打到后端才报 422。 */
const blockingReason = computed(() => {
  if (!profile.canAnalyze) return '请先填写「目标岗位」——后端要求非空。'
  if (mode.value === 'jd' && !jdSourceId.value) return '请选择一份具体 JD。'
  if (mode.value === 'company' && !companySlug.value) return '请选择一家公司。'
  return ''
})

const result = computed(() => analysis.result)
const finalPlan = computed(() => analysis.finalPlan)

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
  rows.push({ key: 'scope', label: '检索范围', value: analysis.jdLabel || '跨公司概览' })
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

  const targetCompany = mode.value === 'company' ? companySlug.value : null
  const sourceId = mode.value === 'jd' ? jdSourceId.value : null

  activeEvidenceRef.value = ''
  analysis.start({
    profile: profile.toRequestProfile(),
    targetJob: profile.targetJob.trim(),
    targetCompany,
    jdSourceId: sourceId,
    jdLabel: targetLabel.value,
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
        提交画像与目标岗位，由 7 个专职 Agent 顺序协作：
        能力画像 → 成长追踪 → 岗位知识库检索（RAG）→ 岗位要求 → 能力差距 → 学习路线 → 实战项目。
      </p>
    </div>

    <!-- 输入区：画像 + 检索范围同处一块沉底表面，白底控件浮在上面 -->
    <section class="panel">
      <ProfileForm />

      <section class="panel-block">
        <div class="panel-head">
          <h2>分析目标</h2>
          <span class="badge badge-primary">{{ targetLabel }}</span>
        </div>

        <div class="field">
          <span id="an-mode-label" class="field-label">检索范围</span>
          <div class="mode-opts" role="radiogroup" aria-labelledby="an-mode-label">
            <label
              v-for="item in TARGET_MODES"
              :key="item.value"
              class="mode-opt"
              :class="{ 'is-on': mode === item.value }"
            >
              <input v-model="mode" type="radio" name="an-mode" :value="item.value" />
              {{ item.label }}
            </label>
          </div>
          <p class="faint block-note">{{ modeHint }}</p>
        </div>

        <div v-if="mode === 'company'" class="field">
          <label for="an-company">公司</label>
          <select id="an-company" v-model="companySlug">
            <option value="">请选择…</option>
            <option v-for="option in companyOptions" :key="option.value" :value="option.value">
              {{ option.label }}（{{ option.value }}）
            </option>
          </select>
        </div>

        <div v-if="mode === 'jd'" class="field">
          <label for="an-jd">具体 JD</label>
          <select id="an-jd" v-model="jdSourceId" :disabled="jdsLoading">
            <option value="">{{ jdsLoading ? '加载中…' : '请选择…' }}</option>
            <option v-for="option in jdOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <p v-if="jdsError" class="notice notice-danger block-note">
            加载 JD 列表失败：{{ jdsError }}
          </p>
          <p v-else-if="!jdsLoading && !jds.length" class="faint block-note">
            知识库里还没有真实 JD（knowledge/jd 为空）。
          </p>
        </div>

        <dl v-if="selectedJd" class="kv kv--narrow notice notice-info">
          <dt>岗位</dt>
          <dd>{{ selectedJd.job_name || '—' }}</dd>
          <dt>公司</dt>
          <dd>{{ selectedJd.company || '—' }}</dd>
          <dt>城市</dt>
          <dd>{{ selectedJd.city || '—' }}</dd>
          <dt>薪资</dt>
          <dd>{{ selectedJd.salary || '—' }}</dd>
          <dt>状态</dt>
          <dd>{{ selectedJd.status || '—' }}</dd>
        </dl>

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
            分析不写成长历史；但首次分析会把产出的学习 / 项目计划存成第 1 轮任务（runs/loop.json）。
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
          :run-id="analysis.runId"
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
          <!-- 汇总：final_plan 由图后的确定性汇总得出，不属于任一 Agent 节点 -->
          <section class="panel">
            <div class="panel-head">
              <h2>结论摘要</h2>
              <span class="panel-src">graph/workflow.py · build_final_plan（非 Agent 节点）</span>
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

          <JdMatchCard :match="analysis.jdMatch" />

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
                    本页分析是<strong>只读</strong>的：不会写入成长历史（runs/growth.json）。
                    成长记录的正式写入发生在「成长记录」页的「生成下一轮」操作中。
                  </p>
                </template>
              </div>
            </section>
          </div>

          <!-- RAG 证据：EvidencePanel 自带 id="card-evidence" -->
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
