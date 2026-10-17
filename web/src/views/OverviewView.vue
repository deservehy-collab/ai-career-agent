<script setup>
import { computed, onMounted, ref } from 'vue'

import AppBadge from '../components/AppBadge.vue'

import { listJds, listTasks } from '../api/endpoints'
import { AGENTS, AGENT_GROUP } from '../utils/agents'
import { useAnalysisStore } from '../stores/analysis'
import { useHealthStore } from '../stores/health'
import { useProfileStore } from '../stores/profile'

/**
 * 概览首页：产品的入口页，不是数据统计后台。
 *
 * 三条纪律
 * --------
 * 1. **只链真实路由**：概览里每个按钮都指向项目里确实存在的页面
 *    （/assistant、/analyze、/tasks、/growth、/status）。
 *    岗位分析、技能差距、学习路线、项目推荐不是独立页面，而是同一条
 *    七节点工作流（graph/workflow.py）里的节点，因此它们的落点明确写成
 *    「结果页内的某个区块」并带锚点 —— 不伪装成独立功能。
 * 2. **数字只来自真实接口**：JD 份数 ← /api/knowledge/jds，
 *    向量条数、技能标准数、模型名 ← /api/health，轮次与完成数 ← /api/tasks。
 *    拿不到就整行不显示，绝不写死数字、假用户或假历史。
 * 3. **纯只读**：本页只发 GET，不会触发了分析、也不会写任何数据。
 */
const health = useHealthStore()
const profile = useProfileStore()
const analysis = useAnalysisStore()

const jdCount = ref(null)
const jdFailed = ref(false)
const taskSummary = ref(null)
const taskFailed = ref(false)

onMounted(async () => {
  if (!health.data && !health.loading) health.refresh()

  try {
    const payload = await listJds()
    jdCount.value = typeof payload?.count === 'number'
      ? payload.count
      : (Array.isArray(payload?.jds) ? payload.jds.length : null)
  } catch {
    jdCount.value = null
    jdFailed.value = true
  }

  try {
    const payload = await listTasks()
    taskSummary.value = payload?.summary && typeof payload.summary.total === 'number'
      ? payload.summary
      : (Array.isArray(payload?.rounds) ? { rounds: payload.rounds.length } : null)
  } catch {
    taskSummary.value = null
    taskFailed.value = true
  }
})

// ── 顶部状态（真实体检结果）─────────────────────────────────────────────
const modelState = computed(() => {
  const data = health.data
  if (health.loading && !data) return { tone: 'warn', text: '正在检测系统状态…' }
  if (health.unreachable) return { tone: 'danger', text: '后端未连接' }
  return data?.status === 'ok'
    ? { tone: 'ok', text: '系统就绪' }
    : { tone: 'warn', text: '降级运行' }
})

const chatModel = computed(() => health.data?.config?.chat_model || '')
const embeddingModel = computed(() => health.data?.config?.embedding_model || '')

// ── 真实读数：本机状态 + 知识库计数。取不到的行整行不渲染 ────────────────
const railRows = computed(() => {
  const data = health.data
  const rows = []
  if (chatModel.value) rows.push({ key: 'chat', label: '生成模型', value: chatModel.value, mono: true })
  if (embeddingModel.value) rows.push({ key: 'embed', label: '嵌入模型', value: embeddingModel.value, mono: true })
  if (jdCount.value !== null) rows.push({ key: 'jd', label: '真实招聘 JD', value: `${jdCount.value} 份` })
  if (data?.index?.ok && typeof data.index.vectors === 'number') {
    rows.push({ key: 'vectors', label: '向量证据', value: `${data.index.vectors} 条` })
  }
  if (data?.knowledge?.skills?.ok && typeof data.knowledge.skills.count === 'number') {
    rows.push({ key: 'skills', label: '技能标准', value: `${data.knowledge.skills.count} 项` })
  }
  if (data?.knowledge?.projects?.ok && typeof data.knowledge.projects.count === 'number') {
    rows.push({ key: 'projects', label: '项目模板', value: `${data.knowledge.projects.count} 个` })
  }
  return rows
})

const railUnavailable = computed(
  () => !health.loading && railRows.value.length === 0 && (health.unreachable || jdFailed.value),
)

// ── 两个独立页面：入口行只指向真实存在的路由 ─────────────────────────────
const entries = [
  {
    key: 'assistant',
    title: 'AI 助手',
    desc: '随时提问：岗位方向、技能学习顺序、简历与项目包装、面试准备。本机模型流式作答，只聊天不动业务数据。',
    to: '/assistant',
    cta: '开始 AI 咨询',
    icon: 'M4 5h16v10H9l-5 4z M8 9h8 M8 12h5',
  },
  {
    key: 'plan',
    title: '求职规划（多 Agent）',
    desc: '七个专职 Agent 顺序协作，一次产出画像、岗位要求、差距、学习路线与项目建议。需要几十秒本机推理时间。',
    to: '/analyze',
    cta: '开始求职规划',
    icon: 'M12 3v4 M12 17v4 M5 12h4 M15 12h4 M8 8l8 8 M16 8l-8 8',
  },
]

/**
 * 工作流产出的落点。岗位分析 / 技能差距 / 学习路线 / 项目推荐不是独立页面，
 * 而是同一条七节点工作流里的节点，所以这里写成结果页内的区块锚点，不伪装成入口。
 */
const outputs = [
  { key: 'jd', label: '岗位分析 · RAG 证据', to: '/analyze', hash: '#card-evidence', where: '结果页证据区' },
  { key: 'gap', label: '技能差距分析', to: '/analyze', hash: '#card-gaps', where: '结果页差距表' },
  { key: 'learning', label: '学习路线', to: '/tasks', where: '学习与项目页' },
  { key: 'project', label: '项目推荐', to: '/tasks', where: '学习与项目页' },
]

// ── 工作流：节点名与顺序与 graph/workflow.py 的 ORDER 一致 ────────────────
const flow = computed(() => AGENTS.map((agent) => ({
  ...agent,
  group: AGENT_GROUP[agent.group],
})))

/** 色族 → 节点数，全部由 AGENTS 现算，不写死。 */
const legend = computed(() => Object.entries(AGENT_GROUP).map(([key, group]) => ({
  key,
  label: group.label,
  color: group.color,
  count: AGENTS.filter((agent) => agent.group === key).length,
})))

/** 能力规格：左列是实现出处（真实文件路径），右列是这条能力现在能做到什么。 */
const spec = computed(() => [
  {
    key: 'multi-agent',
    title: 'Multi-Agent 协同',
    src: 'graph/workflow.py · NODES / ORDER',
    desc: `${AGENTS.length} 个专职 Agent 顺序执行，各自只负责一件事：认知、检索、匹配、规划分段负责，产出可追溯到具体节点与字段。`,
  },
  {
    key: 'rag',
    title: 'RAG 岗位知识库',
    src: 'agents/retriever.py · knowledge/index',
    desc: health.data?.index?.ok
      ? `Chroma 向量库里已有 ${health.data.index.vectors} 条来自真实 JD 的证据片段，检索节点只取事实、不做判定，取不到就降级继续。`
      : '按目标岗位检索真实招聘 JD 的向量库，要求逐条带原文出处；检索未命中时如实降级，不编造岗位要求。',
  },
  {
    key: 'local-llm',
    title: '本地大模型',
    src: 'agents/llm.py · backend/config.py',
    desc: health.data?.ollama?.ok
      ? `推理与嵌入全部走本机 Ollama：生成用 ${health.data.ollama.chat_model}，嵌入用 ${health.data.ollama.embedding_model}，不经云端、不出本机。`
      : '推理与嵌入全部走本机 Ollama（默认 http://localhost:11434），不经云端 API，也不使用云端密钥。',
  },
])

const guide = [
  {
    step: 1,
    title: '先问 AI 助手',
    desc: '不确定方向时，先直接问：需要哪些技能、怎么准备面试。',
    to: '/assistant',
    cta: '去提问',
  },
  {
    step: 2,
    title: '填写个人画像',
    desc: '专业、年级、自述技能与项目经历都在「岗位分析」页左侧填写，保存在本机浏览器并随请求提交（后端没有画像表）。',
    to: '/analyze',
    cta: '去填写画像',
  },
  {
    step: 3,
    title: '生成求职规划',
    desc: '选一份真实 JD 或一家公司发起分析，七个节点跑完会给出岗位要求、差距、学习路线与项目建议。',
    to: '/analyze',
    cta: '开始岗位分析',
  },
  {
    step: 4,
    title: '查看差距与学习建议',
    desc: '技能差距在分析结果页，学习路线与项目任务在「学习与项目」页，完成后可在「成长记录」推进下一轮。',
    to: '/tasks',
    cta: '看学习与项目',
  },
]

// ── 真实进展（只读；没有就显示引导，不编造）───────────────────────────────
const profileFilled = computed(() => profile.canAnalyze)
const roundsText = computed(() => {
  const summary = taskSummary.value
  if (!summary) return ''
  if (typeof summary.rounds === 'number') return `已有 ${summary.rounds} 轮计划`
  return `任务 ${summary.completed ?? 0} / ${summary.total ?? 0} 已完成`
})

const sessionAnalysis = computed(() => {
  if (analysis.status !== 'succeeded' || !analysis.result) return null
  const result = analysis.result
  return {
    targetJob: analysis.targetJob || result.target_job || '未标注目标',
    finishedAt: analysis.finishedAt,
    gaps: Array.isArray(result.skill_gaps) ? result.skill_gaps.length : null,
    learning: Array.isArray(result.learning_plan) ? result.learning_plan.length : null,
    projects: Array.isArray(result.project_plan) ? result.project_plan.length : null,
  }
})
</script>

<template>
  <div class="ov-page">
    <!-- A. 欢迎区：左标题右读数，不套框 -->
    <section class="ov-hero">
      <div>
        <h1>让 AI 帮你规划下一步职业成长</h1>
        <p class="lead">
          面向大学生与应届生的本地化求职规划系统：一个能随时提问的 AI 助手，
          加上一条由 7 个专职 Agent 顺序协作、基于真实招聘 JD 向量知识库的规划工作流。
        </p>
        <div class="ov-hero-actions">
          <router-link class="btn btn-primary" to="/assistant">开始 AI 咨询 →</router-link>
          <router-link class="ov-hero-alt" to="/analyze">或者发起一次求职规划</router-link>
          <AppBadge :text="modelState.text" :tone="modelState.tone" />
        </div>
      </div>

      <div class="ov-rail">
        <p class="ov-rail-title">本机运行读数</p>
        <dl v-if="railRows.length" class="ov-readout" aria-label="本机运行读数">
          <div v-for="row in railRows" :key="row.key">
            <dt>{{ row.label }}</dt>
            <dd :class="{ 'is-mono': row.mono }">{{ row.value }}</dd>
          </div>
        </dl>
        <p v-else-if="railUnavailable" class="faint ov-note">
          读数取不到（后端未连接或数据源缺失）。
          <router-link to="/status">查看系统状态</router-link>
        </p>
        <p v-else class="faint ov-note">正在读取本机状态与知识库计数…</p>
      </div>
    </section>

    <!-- B. 两个独立页面 -->
    <div class="page-head">
      <h2>核心功能</h2>
      <p>只有这两项是独立页面；工作流产出的四项结果，列在下面的链路图后面。</p>
    </div>

    <div class="ov-entries">
      <RouterLink v-for="item in entries" :key="item.key" class="ov-entry" :to="item.to">
        <span class="ov-entry-icon" :aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
               stroke-linecap="round" stroke-linejoin="round">
            <path :d="item.icon" />
          </svg>
        </span>
        <div>
          <h3>{{ item.title }}</h3>
          <p>{{ item.desc }}</p>
        </div>
        <span class="ov-entry-go">
          {{ item.cta }}
          <span class="ov-entry-arrow" aria-hidden="true">→</span>
        </span>
      </RouterLink>
    </div>

    <!-- C. 求职链路：一条脊柱 + 色族图例 + 产出落点 -->
    <section class="panel">
      <div class="panel-head">
        <h2>一条工作流，七个 Agent</h2>
        <span class="panel-src">graph/workflow.py · ORDER</span>
      </div>

      <div class="ov-spine">
        <article
          v-for="agent in flow"
          :key="agent.node"
          class="ov-station"
          :style="{ '--agent-color': agent.group.color }"
        >
          <div class="ov-station-no">
            <span>{{ agent.order }}</span>
            <code>{{ agent.node }}</code>
          </div>
          <h3>{{ agent.displayName }}</h3>
        </article>
      </div>

      <div class="ov-legend">
        <span v-for="item in legend" :key="item.key" class="ov-legend-item">
          <span class="ov-swatch" :style="{ background: item.color }" :aria-hidden="true" />
          {{ item.label }} · {{ item.count }} 个节点
        </span>
      </div>

      <div class="ov-outputs">
        <RouterLink
          v-for="item in outputs"
          :key="item.key"
          class="ov-output"
          :to="item.hash ? `${item.to}${item.hash}` : item.to"
        >
          {{ item.label }}
          <small>{{ item.where }}</small>
        </RouterLink>
      </div>

      <p class="faint ov-note">
        后端只给出整条链路的四个状态（排队 / 运行中 / 成功 / 失败），
        所以运行过程中不做逐节点的假进度显示 —— 结果出来后才会回填每个节点的真实产出条数。
      </p>
    </section>

    <!-- D. 能力规格：左列实现出处，右列现在真的能做到什么 -->
    <section class="panel">
      <div class="panel-head">
        <h2>这套系统靠什么成立</h2>
        <span class="panel-src">backend / agents 源码</span>
      </div>
      <div class="ov-spec">
        <div v-for="item in spec" :key="item.key" class="ov-spec-row">
          <p class="ov-spec-src">{{ item.src }}</p>
          <div>
            <h3 class="ov-spec-title">{{ item.title }}</h3>
            <p>{{ item.desc }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- E. 新手引导 -->
    <section class="panel">
      <div class="panel-head">
        <h2>新手引导</h2>
        <span class="panel-src">建议按这个顺序走一遍</span>
      </div>
      <ol class="guide-list">
        <li v-for="item in guide" :key="item.step" class="guide-item">
          <span class="guide-num">{{ item.step }}</span>
          <div class="guide-text">
            <h3>{{ item.title }}</h3>
            <p>{{ item.desc }}</p>
          </div>
          <RouterLink class="btn btn-ghost btn-sm guide-cta" :to="item.to">{{ item.cta }}</RouterLink>
        </li>
      </ol>
    </section>

    <!-- F. 真实进展 / 空状态引导 -->
    <div class="grid grid-2 ov-cards">
      <section class="card">
        <div class="card-head">
          <h2>
            我的当前状态
            <span class="sub">画像保存在本机浏览器，随请求提交</span>
          </h2>
          <AppBadge :text="profileFilled ? '可以开始分析' : '还差目标岗位'"
                    :tone="profileFilled ? 'ok' : 'warn'" />
        </div>
        <div class="card-body">
          <dl class="kv">
            <dt>目标岗位</dt>
            <dd><strong>{{ profile.targetJob || '未填写' }}</strong></dd>
            <dt>专业 / 年级</dt>
            <dd>{{ profile.major || '—' }} · {{ profile.grade || '—' }}</dd>
            <dt>自述技能</dt>
            <dd>{{ profile.skills.length ? `${profile.skills.length} 项` : '未填写' }}</dd>
            <dt>结构化能力表</dt>
            <dd>{{ profile.lastSkills.length ? `${profile.lastSkills.length} 项（来自最近一次分析）` : '还没有分析结果' }}</dd>
            <dt>任务进度</dt>
            <dd>{{ roundsText || (taskFailed ? '任务清单读取失败' : '还没有轮次任务') }}</dd>
          </dl>
          <div class="btn-row">
            <router-link class="btn btn-primary btn-sm" to="/analyze">
              {{ profileFilled ? '继续岗位分析' : '先填目标岗位' }}
            </router-link>
            <router-link class="btn btn-ghost btn-sm" to="/home">我的档案</router-link>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>
            下一步做什么
            <span class="sub">根据当前真实进度给出</span>
          </h2>
        </div>
        <div class="card-body">
          <div v-if="sessionAnalysis" class="ov-result">
            <p class="muted">
              本次浏览器会话里已经跑完一次分析（结果不会长期缓存，刷新页面即清空），
              目标：<strong>{{ sessionAnalysis.targetJob }}</strong>。
            </p>
            <ul class="ov-result-list">
              <li>技能差距：<strong>{{ sessionAnalysis.gaps ?? 0 }}</strong> 项</li>
              <li>学习阶段：<strong>{{ sessionAnalysis.learning ?? 0 }}</strong> 个</li>
              <li>推荐项目：<strong>{{ sessionAnalysis.projects ?? 0 }}</strong> 个</li>
            </ul>
            <div class="btn-row">
              <router-link class="btn btn-sm" to="/analyze">回看完整结果</router-link>
              <router-link class="btn btn-ghost btn-sm" to="/tasks">执行学习与项目任务</router-link>
            </div>
          </div>

          <div v-else-if="roundsText" class="ov-result">
            <p>{{ roundsText }}。可以提交任务完成证据，再在「成长记录」生成下一轮计划。</p>
            <div class="btn-row">
              <router-link class="btn btn-sm" to="/tasks">去学习与项目</router-link>
              <router-link class="btn btn-ghost btn-sm" to="/growth">成长记录</router-link>
            </div>
          </div>

          <div v-else class="empty ov-result">
            <p>
              这台浏览器上还没有属于你的规划结果。两条起步路径：
            </p>
            <ul>
              <li>有具体问题想先聊 → <router-link to="/assistant">AI 助手</router-link>（只聊天，不动业务数据）</li>
              <li>想要完整方案 → 在<router-link to="/analyze">岗位分析</router-link>填好目标岗位后发起一次分析</li>
            </ul>
            <p class="faint">
              分析会真实调用本机模型的 7 次推理，通常需要几十秒；期间可以切到
              <router-link to="/status">系统状态</router-link>确认 Ollama 就绪。
            </p>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
