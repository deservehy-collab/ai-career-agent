/**
 * localStorage 读写小工具。
 *
 * 画像**不做后端持久化**（后端没有画像接口），由前端保存、每次请求携带。
 * 两个键分开存，语义不同、不要混：
 *   career-agent:profile      —— 用户自述：major / grade / skills(字符串数组) / projects / target_job
 *   career-agent:last-skills  —— 最近一次分析返回的**结构化能力表** [{skill, level, evidence}]
 *
 * 后者是提交任务完成时 `profile_skills` 的来源（让"升级预览"与下一轮真实判定同一基线）。
 */

export const PROFILE_KEY = 'career-agent:profile'
export const LAST_SKILLS_KEY = 'career-agent:last-skills'

/** localStorage 不可用时（隐私模式 / 被禁用）也不能让页面崩掉。 */
function safeStorage() {
  try {
    const probe = '__career_agent_probe__'
    window.localStorage.setItem(probe, '1')
    window.localStorage.removeItem(probe)
    return window.localStorage
  } catch {
    return null
  }
}

export function readJson(key, fallback) {
  const storage = safeStorage()
  if (!storage) return fallback
  try {
    const raw = storage.getItem(key)
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    return parsed ?? fallback
  } catch {
    // 存的内容坏了就当没有 —— 不删用户数据，只是本次不用
    return fallback
  }
}

/**
 * 写入 JSON。
 * @returns {boolean} 是否写入成功（配额满 / 被禁用时返回 false，由调用方决定是否提示）
 */
export function writeJson(key, value) {
  const storage = safeStorage()
  if (!storage) return false
  try {
    storage.setItem(key, JSON.stringify(value))
    return true
  } catch {
    return false
  }
}

export function removeKey(key) {
  const storage = safeStorage()
  if (!storage) return
  try {
    storage.removeItem(key)
  } catch {
    /* 忽略 */
  }
}

/** 把多行 / 顿号 / 逗号分隔的文本解析成去重后的字符串数组。 */
export function parseList(text) {
  if (Array.isArray(text)) return text.map((s) => String(s).trim()).filter(Boolean)
  return String(text || '')
    .split(/[\n,，、;；]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** 数组 → 便于编辑的多行文本。 */
export function formatList(list) {
  return Array.isArray(list) ? list.join('\n') : ''
}
