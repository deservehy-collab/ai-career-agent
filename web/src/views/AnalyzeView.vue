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
import { AGENT_GROUP, summarizeWorkflow } from '../utils/agents'
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

// ── 成长节点（agents/growth_agent.py 的 growth_diff）────────────────────
const growthDiff = computed(() => result.value?.growth_diff || null)
const levelChanges = computed(() => growthDiff.value?.level_changes || [])
const blockedUpgrades = computed(() => growthDiff.value?.blocked_upgrades || [])
const growthWarnings = computed(() => growthDiff.value?.warnings || [])
const baselineSkills = computed(() => result.value?.user_skills_before || [])
const cognitionStyle = computed(() => ({
  '--agent-color': AGENT_GROUP.cognition.color,
  '--agent-soft': AGENT_GROUP.cognition.soft,
}))

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

    <ProfileForm />

    <!-- 分析目标 -->
    <section class="card">
      <div class="card-head">
        <h2>
          分析目标
          <span class="sub">限定检索范围，决定「真实 JD 匹配」这一节的具体程度</span>
        </h2>
        <AppBadge :text="targetLabel" tone="primary" />
      </div>

      <div class="card-body">
        <div class="field">
          <label>检索范围</label>
          <div class="btn-row">
            <label v-for="item in TARGET_MODES" :key="item.value" class="btn" style="font-weight: 500">
              <input v-model="mode" type="radio" :value="item.value" style="width: auto; margin-right: 6px" />
              {{ item.label }}
            </label>
          </div>
          <p class="faint" style="margin: 6px 0 0">
            {{ TARGET_MODES.find((m) => m.value === mode)?.hint }}
          </p>
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
          <p v-if="jdsError" class="faint" style="color: var(--danger); margin: 6px 0 0">
            加载 JD 列表失败：{{ jdsError }}
          </p>
          <p v-else-if="!jdsLoading && !jds.length" class="faint" style="margin: 6px 0 0">
            知识库里还没有真实 JD（knowledge/jd 为空）。
          </p>
        </div>

        <div v-if="selectedJd" class="notice notice-info" style="margin-top: 4px">
          <dl class="kv" style="grid-template-columns: 72px 1fr">
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
        </div>

        <div v-if="blockingReason" class="notice notice-warn" style="margin-top: 14px">
          {{ blockingReason }}
        </div>

        <div class="btn-row" style="margin-top: 14px">
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
          <span class="faint">分析为只读操作，不会写入任何成长或任务记录。</span>
        </div>
      </div>
    </section>

    <!-- 两栏工作区：左流程轨 + 右结果 -->
    <div v-if="showWorkspace" class="layout-rail">
      <aside class="rail">
        <AgentPipeline :summary="workflowSummary" :status="analysis.status" />
      </aside>

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

        <template v-if="result">
          <!-- 汇总：final_plan 由图后的确定性汇总得出，不属于任一 Agent 节点 -->
          <section class="card">
            <div class="card-head">
              <h2>
                结论摘要
                <span class="sub">
                  图后汇总（build_final_plan，非 Agent 节点）
                  · {{ finalPlan?.target_job || analysis.targetJob }} · {{ analysis.jdLabel }}
                </span>
              </h2>
              <AppBadge
                v-if="finalPlan"
                :text="`${finalPlan.learning_stage_count} 个学习阶段 · ${finalPlan.recommended_projects?.length || 0} 个项目`"
                tone="primary"
              />
            </div>
            <div class="card-body">
              <div class="notice notice-info" v-if="finalPlan?.next_action">
                <strong>下一步：</strong>{{ finalPlan.next_action }}
              </div>
              <div class="grid grid-2">
                <div>
                  <h3 style="font-size: 13px">最需要补的缺口</h3>
                  <div class="tags" style="margin-top: 8px">
                    <span v-for="gap in finalPlan?.top_gaps || []" :key="gap" class="badge badge-danger">
                      {{ gap }}
                    </span>
                    <span v-if="!(finalPlan?.top_gaps || []).length" class="faint">没有高优先级缺口</span>
                  </div>
                </div>
                <div>
                  <h3 style="font-size: 13px">已满足的岗位要求</h3>
                  <div class="tags" style="margin-top: 8px">
                    <span v-for="skill in finalPlan?.already_satisfied || []" :key="skill" class="badge badge-ok">
                      {{ skill }}
                    </span>
                    <span v-if="!(finalPlan?.already_satisfied || []).length" class="faint">暂无</span>
                  </div>
                </div>
              </div>
              <p class="faint" style="margin-bottom: 0; margin-top: 14px">
                推荐项目：{{ joinList(finalPlan?.recommended_projects) }}
              </p>
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
            <section class="card accent-left" :style="cognitionStyle">
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
                  <div class="metric-strip" style="margin-bottom: 14px">
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

                  <div v-if="baselineSkills.length" style="margin-bottom: 12px">
                    <h3 style="font-size: 13px">合并历史后的能力基线</h3>
                    <div class="tags" style="margin-top: 8px">
                      <span v-for="item in baselineSkills" :key="item.skill">
                        <AppBadge
                          :text="`${item.skill} · ${item.level || '无'}`"
                          :tone="levelTone(item.level)"
                        />
                      </span>
                    </div>
                  </div>

                  <div v-if="levelChanges.length">
                    <h3 style="font-size: 13px">技能等级变化</h3>
                    <ul style="margin: 6px 0 0; padding-left: 18px" class="muted">
                      <li v-for="item in levelChanges" :key="item.skill">
                        {{ item.skill }}：{{ item.from || '无' }} → {{ item.to }}
                        <span v-if="item.source" class="faint">（来源成果：{{ item.source }}）</span>
                      </li>
                    </ul>
                  </div>

                  <div v-if="blockedUpgrades.length" style="margin-top: 12px">
                    <h3 style="font-size: 13px">被前置门禁拦下的升级</h3>
                    <ul style="margin: 6px 0 0; padding-left: 18px" class="muted">
                      <li v-for="item in blockedUpgrades" :key="item.skill">
                        {{ item.skill }}（缺前置：{{ joinList(item.missing_prerequisites, '未给出') }}）
                      </li>
                    </ul>
                  </div>

                  <div v-for="(warn, i) in growthWarnings" :key="i" class="notice notice-warn">
                    {{ warn }}
                  </div>

                  <p class="faint" style="margin: 12px 0 0">
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
