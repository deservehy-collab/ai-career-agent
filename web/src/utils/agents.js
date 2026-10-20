/**
 * 7 个 Agent 的静态元数据 + 由分析结果反推的"各节点产出摘要"。
 *
 * 两条硬规矩
 * ----------
 * 1. **可追溯**：每个条目都保留 `node` —— 与 `graph/workflow.py` 的 `NODES` / `ORDER`
 *    里的实际节点名逐字一致。展示名可以面向评委优化，但绝不能与真实节点失去对应关系。
 *    源码路径**不再进界面**：使用者只看中文展示名与职责，实现细节回代码里查。
 *
 * 2. **不虚构执行状态**：后端只给四态（queued/running/succeeded/failed），
 *    `TaskRecord` 里**没有任何节点级信息**，且工作流是**纯顺序图、无条件边** ——
 *    7 个节点每次都会执行。所以这里：
 *      - 只描述**静态结构**（顺序 / 职责，来自代码）；
 *      - 只有**拿到 result 之后**才回填产出摘要；
 *      - 运行中不给任何单个节点标"运行中"；
 *      - 失败时不指向具体节点（后端只给一个错误字符串，定位不了）。
 */

/** 与 graph/workflow.py 的 ORDER 完全一致。 */
export const WORKFLOW_ORDER = [
  'profile',
  'growth',
  'retrieval',
  'job',
  'assessment',
  'learning',
  'project',
]

/** 色族：认知 / 依据 / 匹配 / 规划。依据整理单独一色，是全站唯一的紫。 */
export const AGENT_GROUP = {
  cognition: { label: '认知', color: 'var(--agent-cognition)', soft: 'var(--agent-cognition-soft)' },
  retrieval: { label: '依据', color: 'var(--agent-retrieval)', soft: 'var(--agent-retrieval-soft)' },
  match: { label: '匹配', color: 'var(--agent-match)', soft: 'var(--agent-match-soft)' },
  plan: { label: '规划', color: 'var(--agent-plan)', soft: 'var(--agent-plan-soft)' },
}

export const AGENTS = [
  {
    node: 'profile',
    order: 1,
    displayName: '能力画像 Agent',
    group: 'cognition',
    duty: '读取专业 / 年级 / 自述技能 / 项目经历，按证据分级产出结构化能力表，并给出技术优势与短板。',
    outputs: ['user_skills', 'user_strengths', 'user_weaknesses'],
    primaryKey: 'user_skills',
    anchor: 'card-profile',
    outputLabel: '项能力',
  },
  {
    node: 'growth',
    order: 2,
    displayName: '成长追踪 Agent',
    group: 'cognition',
    duty: '合并成长历史与本次画像作为基线，按本轮成长事件升级技能等级，并记录升级前后的差异。',
    outputs: ['user_skills_before', 'skill_updates', 'growth_diff'],
    primaryKey: 'growth_diff',
    anchor: 'card-growth',
    outputLabel: '项等级变化',
  },
  {
    node: 'retrieval',
    order: 3,
    displayName: '招聘原文整理 Agent',
    group: 'retrieval',
    duty: '把你粘贴的招聘要求原文逐句切开，作为本次分析的唯一事实依据。只整理原话，不做任何判定，也不写学生能力。',
    outputs: ['job_evidence', 'retrieval_status', 'retrieval_diagnostics'],
    primaryKey: 'job_evidence',
    anchor: 'card-evidence',
    outputLabel: '句原话',
  },
  {
    node: 'job',
    order: 4,
    displayName: '岗位要求 Agent',
    group: 'match',
    duty: '逐条从粘贴的招聘要求原文里抽出能力要求，并标注每条要求在原文里的出处与证据强度。',
    outputs: ['job_requirements'],
    primaryKey: 'job_requirements',
    anchor: 'card-requirements',
    outputLabel: '项要求',
  },
  {
    node: 'assessment',
    order: 5,
    displayName: '能力差距 Agent',
    group: 'match',
    duty: '把岗位要求与学生能力逐项对照。等级 / 状态 / 优先级全部由代码判定，不由模型自由发挥。',
    outputs: ['skill_gaps'],
    primaryKey: 'skill_gaps',
    anchor: 'card-gaps',
    outputLabel: '项差距',
  },
  {
    node: 'learning',
    order: 6,
    displayName: '学习路线 Agent',
    group: 'plan',
    duty: '按缺口优先级与技能前置关系排出学习阶段，每个阶段给出目标、前置要求与可验证的完成标准。',
    outputs: ['learning_plan'],
    primaryKey: 'learning_plan',
    anchor: 'card-learning',
    outputLabel: '个阶段',
  },
  {
    node: 'project',
    order: 7,
    displayName: '实战项目 Agent',
    group: 'plan',
    duty: '结合技能缺口与学习路线推荐实战项目，给出技术栈、对应阶段与可验收的最终成果。',
    outputs: ['project_plan'],
    primaryKey: 'project_plan',
    anchor: 'card-projects',
    outputLabel: '个项目',
  },
]

const BY_NODE = new Map(AGENTS.map((agent) => [agent.node, agent]))

export function getAgent(node) {
  return BY_NODE.get(node) ?? null
}

export function agentColor(node) {
  const agent = BY_NODE.get(node)
  return agent ? AGENT_GROUP[agent.group].color : 'var(--text-muted)'
}

// ── 产出摘要（只在拿到 result 后调用）────────────────────────────────────

function countOf(value) {
  return Array.isArray(value) ? value.length : 0
}

/**
 * 单节点摘要。
 *
 * 三种状态必须分清楚，**不许把"没有数据"一律说成"节点没产出"**：
 *
 *   present=false —— 结果里**根本没有**该节点的产出字段。我们对这个节点一无所知，
 *                    只能说"没有数据"，不能断言它没产出（那是猜测）。
 *   present=true, count=0 —— 字段在、但是空数组：节点确实产出了 0 条，如实说。
 *   degraded —— 在 count 的基础上，再用后端自己的状态字段判断是否走了降级路径。
 *
 * `degraded` 的判据**全部来自真实字段**：
 *   - profile / job / assessment / learning / project：产出数组为空
 *   - retrieval：`retrieval_status !== 'user_pasted'`（后端只会给 user_pasted / no_source）
 *   - growth：`growth_diff.outcome` 为 `store_unreadable` 或 `gate_unavailable`
 *     （注意：`no_events` **不是**降级 —— 本轮本来就没有成长事件，属正常）
 */
function summarizeNode(agent, result) {
  const has = (key) => Object.prototype.hasOwnProperty.call(result, key)

  // 该节点的"主产出字段"不在结果里 → 无从判断，中性表述
  if (!has(agent.primaryKey)) {
    return { present: false, count: 0, degraded: false, note: '结果里没有该节点的产出字段' }
  }

  const growthDiff = result.growth_diff || {}

  switch (agent.node) {
    case 'profile': {
      const count = countOf(result.user_skills)
      return { present: true, count, degraded: count === 0, note: count === 0 ? '未解析出任何技能' : '' }
    }
    case 'growth': {
      const outcome = growthDiff.outcome
      const count = countOf(result.skill_updates)
      return {
        present: true,
        count,
        degraded: outcome === 'store_unreadable' || outcome === 'gate_unavailable',
        // no_events 是"正常但没有"，措辞要和"降级"分开
        note: outcome === 'no_events' ? '本轮无成长事件，未升级任何等级（正常）' : '',
        outcome: outcome ?? null,
      }
    }
    case 'retrieval': {
      const status = result.retrieval_status || ''
      const count = countOf(result.job_evidence)
      const statusOk = status === 'user_pasted'
      // 正常情况下 status=user_pasted 必然切出原话；两者矛盾时按"有问题"处理，
      // 不要因为状态字段好看就把零证据显示成正常。
      let note = ''
      if (!statusOk) note = '没有可用的招聘原文，岗位要求改由模型推断（已如实标注）'
      else if (count === 0) note = '状态显示用了原文，却没切出任何句子'
      return {
        present: true,
        count,
        degraded: !statusOk || count === 0,
        note,
        status,
      }
    }
    case 'job': {
      const count = countOf(result.job_requirements)
      return { present: true, count, degraded: count === 0, note: count === 0 ? '未生成岗位要求' : '' }
    }
    case 'assessment': {
      const count = countOf(result.skill_gaps)
      return { present: true, count, degraded: count === 0, note: count === 0 ? '未生成能力差距' : '' }
    }
    case 'learning': {
      const count = countOf(result.learning_plan)
      return { present: true, count, degraded: count === 0, note: count === 0 ? '未生成学习阶段' : '' }
    }
    case 'project': {
      const count = countOf(result.project_plan)
      return { present: true, count, degraded: count === 0, note: count === 0 ? '未推荐项目' : '' }
    }
    default:
      return { present: false, count: 0, degraded: false, note: '' }
  }
}

/**
 * 把分析结果摊成「节点 → 产出摘要」。
 * result 为空（未运行 / 运行中）时返回 null —— 调用方据此渲染"未产出"的中性格。
 */
export function summarizeWorkflow(result) {
  if (!result) return null
  const summary = {}
  for (const agent of AGENTS) summary[agent.node] = summarizeNode(agent, result)
  return summary
}
