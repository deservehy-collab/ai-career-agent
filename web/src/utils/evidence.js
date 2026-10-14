/**
 * 证据编号 ↔ `job_evidence` 数组位置的映射。
 *
 * 后端规则（agents/job_agent.py::evidence_ref）:
 *     def evidence_ref(index): return f"E{index + 1:02d}"
 * 即 **编号 = 数组下标 + 1**，E01 对应 job_evidence[0]。
 *
 * 「岗位要求 ↔ 原始证据」的可追溯性完全建立在这个位置关系上，
 * 所以规则只在这里写一次，U3 的证据面板与 U4 的岗位要求表共用同一份实现 ——
 * 两处各写一遍迟早会漂移。
 */

/** 与 Python 的 `f"E{index + 1:02d}"` 逐字对齐（两位起步，超过 99 自然变三位）。 */
export function evidenceCode(index) {
  return `E${String(Number(index) + 1).padStart(2, '0')}`
}

/** 编号反解成数组下标；格式不合法返回 null（不猜、不硬凑）。 */
export function codeIndex(code) {
  const match = /^E(\d{2,})$/.exec(String(code || '').trim().toUpperCase())
  if (!match) return null
  return Number(match[1]) - 1
}

/** 构造 `{ 编号: {item, index} }`，只收录下标确实存在的编号。 */
export function buildEvidenceIndex(evidence) {
  const map = {}
  if (!Array.isArray(evidence)) return map
  evidence.forEach((item, index) => {
    map[evidenceCode(index)] = { item, index }
  })
  return map
}

/**
 * 反向引用：`{ 编号: [引用了这条证据的岗位要求技能名, ...] }`。
 * 依据 `job_requirements[].evidence_refs`（同样是一串 E 编号）。
 * 编号不在证据范围内的会被跳过 —— 那是脏数据，不往界面上搬。
 */
export function buildReferencedBy(requirements, evidence) {
  const map = {}
  if (!Array.isArray(requirements)) return map
  const known = Array.isArray(evidence) ? new Set(evidence.map((_, i) => evidenceCode(i))) : null

  for (const requirement of requirements) {
    const refs = Array.isArray(requirement?.evidence_refs) ? requirement.evidence_refs : []
    for (const raw of refs) {
      const code = String(raw || '').trim().toUpperCase()
      if (!code) continue
      if (known && !known.has(code)) continue
      if (!map[code]) map[code] = []
      const skill = String(requirement?.skill || '').trim()
      if (skill && !map[code].includes(skill)) map[code].push(skill)
    }
  }
  return map
}
