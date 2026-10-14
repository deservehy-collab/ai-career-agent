/**
 * 后端枚举值 → 中文 + 视觉基调。
 * 取值全部来自实际代码（agents/ 与 backend/），不确定的一律落到"中性显示"，
 * 绝不猜测成一个看起来更漂亮的词。
 */

function lookup(map, value, fallback = null) {
  if (value === null || value === undefined || value === '') return fallback ?? '—'
  return map[value] ?? fallback ?? String(value)
}

// ── 岗位匹配总评（agents/jd_match.py）──────────────────────────────────
const JD_OVERALL = {
  satisfied: { text: '已满足', tone: 'ok' },
  partial: { text: '部分满足', tone: 'warn' },
  insufficient: { text: '证据不足，无法判定', tone: 'muted' },
}

export function jdOverallText(value) {
  return lookup(
    { satisfied: '已满足', partial: '部分满足', insufficient: '证据不足，无法判定' },
    value,
  )
}

export function jdOverallTone(value) {
  return JD_OVERALL[value]?.tone ?? 'muted'
}

// ── 技能缺口（agents/assessment_agent.py）──────────────────────────────
const GAP_STATUS_TONE = {
  已满足: 'ok',
  部分满足: 'warn',
  明显不足: 'danger',
}

export function gapStatusTone(value) {
  return GAP_STATUS_TONE[value] ?? 'muted'
}

export function priorityTone(value) {
  return { 高: 'danger', 中: 'warn', 低: 'muted' }[value] ?? 'muted'
}

// ── 技能等级（agents/utils.py SKILL_LEVELS，四档固定）───────────────────
export const SKILL_LEVELS = ['入门', '初级', '中级', '高级']

export function levelTone(value) {
  return { 入门: 'muted', 初级: 'warn', 中级: 'primary', 高级: 'ok' }[value] ?? 'muted'
}

// ── 证据强度（agents/job_agent.py 的 _attach_evidence）─────────────────
// 真实取值只有三个：supported / partially_supported / model_supplement。
//   supported           —— 技能名与证据完全同名，且规则层直接命中
//   partially_supported —— 仅靠别名/语义相关，证据强度弱于前者
//   model_supplement    —— 证据里根本没有，这条要求是模型补充的（**不等于有证据**）
// 文案与色调都从这里取，避免同一套词在 Text / Tone 两处各写一遍而漂移。
const EVIDENCE_STATUS = {
  supported: { text: '有直接证据', tone: 'ok' },
  partially_supported: { text: '仅弱证据（别名/语义相关）', tone: 'warn' },
  model_supplement: { text: '模型补充（无知识库证据）', tone: 'warn' },
}

export function evidenceStatusText(value) {
  return EVIDENCE_STATUS[value]?.text ?? (value ? String(value) : '—')
}

export function evidenceStatusTone(value) {
  return EVIDENCE_STATUS[value]?.tone ?? 'muted'
}

/** 这条要求是否真的被知识库证据支撑（model_supplement 不算）。 */
export function hasKnowledgeBaseEvidence(value) {
  return value === 'supported' || value === 'partially_supported'
}

// ── 判断依据来源（agents/job_agent.py）─────────────────────────────────
// importance_basis：profile_skill_importance（沿用岗位画像的人工评级）/ model_generated（模型给的）
const IMPORTANCE_BASIS = {
  profile_skill_importance: { text: '来自岗位画像评级', tone: 'ok' },
  model_generated: { text: '模型生成', tone: 'muted' },
}

export function importanceBasisText(value) {
  return IMPORTANCE_BASIS[value]?.text ?? (value ? String(value) : '—')
}

export function importanceBasisTone(value) {
  return IMPORTANCE_BASIS[value]?.tone ?? 'muted'
}

// level_basis.origin 的三个真实取值：
//   jd_text       —— JD 原文里明确写了等级措辞（带 quote 原文）
//   profile_level —— 岗位画像里该技能标注的等级
//   model_inferred—— 模型自己推断的（**JD 没写等级**，不等于 JD 写了）
const LEVEL_ORIGIN = {
  jd_text: { text: 'JD 原文写明', tone: 'ok' },
  profile_level: { text: '岗位画像标注', tone: 'primary' },
  model_inferred: { text: '模型推断（JD 未写明）', tone: 'muted' },
}

export function levelOriginText(value) {
  return LEVEL_ORIGIN[value]?.text ?? (value ? String(value) : '—')
}

export function levelOriginTone(value) {
  return LEVEL_ORIGIN[value]?.tone ?? 'muted'
}

// ── 检索状态（agents/retriever.py STATUS_*）────────────────────────────
const RETRIEVAL_STATUS = {
  matched: '命中',
  not_mentioned: '知识库未提及',
  no_source: '无可用来源',
  ambiguous: '命中不唯一，需澄清',
}

export function retrievalStatusText(value) {
  return lookup(RETRIEVAL_STATUS, value)
}

export function retrievalStatusTone(value) {
  return { matched: 'ok', ambiguous: 'warn', not_mentioned: 'muted', no_source: 'warn' }[value] ?? 'muted'
}

// 命中路径（agents/retriever.py diagnostics["match_kind"]）—— 决定这次 RAG 的可信度。
//   exact_skill —— 技能精确/别名匹配 + 全量核对（最可靠）
//   overview    —— 整体性问题，按技能聚合，跨公司体现共性
//   vector_only —— 只由语义相似度排序，**未经技能词校验**，可信度最低
//   term_scan   —— 内容词在资料里完全找不到，判为未提及
const MATCH_KIND = {
  exact_skill: { text: '技能精确匹配 + 全量核对', tone: 'ok' },
  overview: { text: '整体聚合（按技能汇总跨公司共性）', tone: 'primary' },
  vector_only: { text: '仅向量语义排序（未经技能词校验）', tone: 'warn' },
  term_scan: { text: '词面核对未找到', tone: 'muted' },
}

export function matchKindText(value) {
  return MATCH_KIND[value]?.text ?? (value ? String(value) : '—')
}

export function matchKindTone(value) {
  return MATCH_KIND[value]?.tone ?? 'muted'
}

// diagnostics["reason"] 有两种形态（agents/retriever.py）：
//   - 大多数情况下是**完整的中文句子**（如"查询涉及多家公司，需要澄清后再检索…"）→ 原样透出
//   - 少数是**机器标识**（index_missing / index_unavailable）→ 必须翻译，不能把英文标识直接摆给用户看
const RETRIEVAL_REASON_TOKENS = {
  index_missing: '向量索引不存在（尚未构建，可运行 scripts/build_index.py 重建）',
  index_unavailable: '向量索引无法打开（后端异常，详见下方错误）',
}

export function retrievalReasonText(value) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  return RETRIEVAL_REASON_TOKENS[text] ?? text
}

// 单条证据的来源路径（agents/retriever.py 给每条 evidence 打的 "origin"）。
// 三个真实取值，决定"这条证据是怎么被找到的"：
const EVIDENCE_ORIGIN = {
  skill_exact: { text: '技能精确匹配', tone: 'ok' },
  vector: { text: '向量语义召回', tone: 'warn' },
  overview: { text: '整体聚合（跨公司共性）', tone: 'primary' },
}

export function evidenceOriginText(value) {
  return EVIDENCE_ORIGIN[value]?.text ?? (value ? String(value) : '—')
}

export function evidenceOriginTone(value) {
  return EVIDENCE_ORIGIN[value]?.tone ?? 'muted'
}

// ── 任务（agents/loop_store.py）────────────────────────────────────────
export function taskKindText(value) {
  return lookup({ learning: '学习任务', project: '项目任务' }, value)
}

export function taskKindTone(value) {
  return { learning: 'primary', project: 'ok' }[value] ?? 'muted'
}

export function taskStatusText(value) {
  return lookup({ pending: '待完成', completed: '已完成' }, value)
}

export function taskStatusTone(value) {
  return { pending: 'muted', completed: 'ok' }[value] ?? 'muted'
}

// ── 提交任务完成的整体结论（agents/growth_loop.py LOOP_*）───────────────
// ⚠️ 这四个值描述的是"整次提交"的结果，**不等于**技能真的升级了 —— 升级只是预览。
const LOOP_STATUS = {
  completed_upgraded: { text: '任务已完成；有升级预览（尚未落盘）', tone: 'primary' },
  completed_no_upgrade: { text: '任务已完成；本次没有升级预览', tone: 'muted' },
  completed_no_growth_event: { text: '任务已完成；但构不成长成果', tone: 'warn' },
  completion_failed: { text: '任务完成记录未写入', tone: 'danger' },
}

export function loopStatusText(value) {
  return LOOP_STATUS[value]?.text ?? (value ? String(value) : '—')
}

export function loopStatusTone(value) {
  return LOOP_STATUS[value]?.tone ?? 'muted'
}

// ── 任务完成记录本身的写入状态（loop_store COMPLETE_*）─────────────────
const COMPLETION_STATUS = {
  completed: { text: '已写入任务记录', tone: 'ok' },
  already_completed: { text: '此前已完成，本次未改动磁盘', tone: 'muted' },
  unknown_task: { text: '任务不存在', tone: 'danger' },
  invalid_task_id: { text: '任务 ID 格式不合法', tone: 'danger' },
  invalid_evidence: { text: '证据格式不合法', tone: 'danger' },
}

export function completionStatusText(value) {
  return COMPLETION_STATUS[value]?.text ?? (value ? String(value) : '—')
}

export function completionStatusTone(value) {
  return COMPLETION_STATUS[value]?.tone ?? 'muted'
}

// ── 成长成果的构造状态（growth_loop EVENT_*）───────────────────────────
// 构不成果 ≠ 任务没完成；只是这条任务无法产生技能升级的依据。
const EVENT_STATUS = {
  ok: { text: '已构造成长成果', tone: 'ok' },
  no_evidence: { text: '未构造成果：没有填写证据', tone: 'warn' },
  no_skills: { text: '未构造成果：任务没有关联技能', tone: 'warn' },
  unknown_kind: { text: '未构造成果：任务类型未知', tone: 'danger' },
  invalid_task: { text: '未构造成果：任务数据不合法', tone: 'danger' },
}

export function eventStatusText(value) {
  return EVENT_STATUS[value]?.text ?? (value ? String(value) : '—')
}

export function eventStatusTone(value) {
  return EVENT_STATUS[value]?.tone ?? 'muted'
}

// ── 升级预览所用的基线（agents/growth_loop.py）─────────────────────────
//   profile_merged —— 历史 ∪ 本次画像，与 growth_node 完全一致（准）
//   history_only   —— 本次拿不到画像，只按历史算，**比真实判定更严格**
const BASELINE_SOURCE = {
  profile_merged: { text: '历史 ∪ 画像（与正式判定同基线）', tone: 'ok' },
  history_only: { text: '仅成长历史（未计入画像，偏严格）', tone: 'warn' },
}

export function baselineSourceText(value) {
  return BASELINE_SOURCE[value]?.text ?? (value ? String(value) : '—')
}

export function baselineSourceTone(value) {
  return BASELINE_SOURCE[value]?.tone ?? 'muted'
}

// ── 技能知识库加载状态（growth_rules KB_STATUS_*）──────────────────────
export function knowledgeBaseStatusText(value) {
  return lookup({ ok: '正常', load_failed: '加载失败（前置门禁未执行）' }, value)
}

export function knowledgeBaseStatusTone(value) {
  return { ok: 'ok', load_failed: 'warn' }[value] ?? 'muted'
}

// ── 运行状态（backend/jobs.py）────────────────────────────────────────
export function runStatusText(value) {
  return lookup(
    { queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败' },
    value,
  )
}

export function runStatusTone(value) {
  return { queued: 'muted', running: 'primary', succeeded: 'ok', failed: 'danger' }[value] ?? 'muted'
}

// ── 存储状态（agents/*_store.py）──────────────────────────────────────
export function storeStatusText(value) {
  return lookup(
    {
      ok: '正常',
      empty: '空（首次运行，尚未创建文件）',
      corrupt: '已损坏（未被覆盖，需人工处理）',
      unreadable: '不可读（权限/占用）',
      schema_mismatch: '版本不匹配（不擅自迁移）',
    },
    value,
  )
}

export function storeStatusTone(value) {
  return { ok: 'ok', empty: 'muted', corrupt: 'danger', unreadable: 'danger', schema_mismatch: 'warn' }[value] ?? 'muted'
}

// ── 成长结论 / 前置门禁（agents/growth_agent.py、growth_rules.py）──────
// F1 不在界面上使用，但一次建好，后续页面直接复用，避免两处写法漂移。
export function growthOutcomeText(value) {
  return lookup(
    {
      upgraded: '有技能等级提升',
      no_upgrade: '有事件，但没有产生等级变化',
      no_events: '本轮没有成长事件',
      all_duplicates: '事件都是历史重复，未重复升级',
      blocked_by_prerequisites: '升级被前置技能门禁拦下',
      gate_unavailable: '知识库不可用，前置门禁未执行',
      invalid_events: '事件不合法，已跳过',
      store_unreadable: '成长历史无法读取（已按 profile 基线继续）',
    },
    value,
  )
}

export function growthOutcomeTone(value) {
  return (
    {
      upgraded: 'ok',
      no_upgrade: 'muted',
      no_events: 'muted',
      all_duplicates: 'muted',
      blocked_by_prerequisites: 'warn',
      gate_unavailable: 'warn',
      invalid_events: 'warn',
      store_unreadable: 'danger',
    }[value] ?? 'muted'
  )
}

export function gateStatusText(value) {
  return lookup(
    {
      passed: '已通过（技能已收录且前置齐备）',
      not_covered: '已跳过（该技能未收录等级标准）',
      unavailable: '未执行（知识库加载失败）',
      blocked: '被拦截（前置技能不足）',
    },
    value,
  )
}

export function gateStatusTone(value) {
  return { passed: 'ok', not_covered: 'muted', unavailable: 'warn', blocked: 'danger' }[value] ?? 'muted'
}
