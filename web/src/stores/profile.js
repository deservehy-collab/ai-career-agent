/**
 * 用户画像（会话内状态 + 分析产物持久化）。
 *
 * 两个语义不同的东西，**分开对待**：
 *
 *   1. 自述信息 `{major, grade, skills: string[], projects: string[]}`
 *      → 就是后端 `UserProfileRequest` 的四个字段，用户自己填的。
 *      **只在内存里活一个会话**：每次刷新页面都清空（用户明确要求）——
 *      上一次分析填的专业/岗位不该悄悄溜进下一次分析。后端没有画像接口。
 *   2. 最近一次分析返回的**结构化能力表** `[{skill, level, evidence}]`
 *      → 用户填不出来，只能由分析产生，且是几分钟推理换来的，
 *        **持久化到 localStorage**（LAST_SKILLS_KEY），提交任务完成时当
 *        `profile_skills` 回传，让"升级预览"和下一轮 growth_node 用同一基线
 *        （见 backend/schemas.py 的说明）。删除需用户明确操作。
 */

import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { LAST_SKILLS_KEY, readJson, writeJson } from '../utils/storage'

function loadInitialSkills() {
  const saved = readJson(LAST_SKILLS_KEY, null)
  if (!saved || typeof saved !== 'object') return { skills: [], at: null }
  return {
    skills: Array.isArray(saved?.skills) ? saved.skills : [],
    at: typeof saved.at === 'string' ? saved.at : null,
  }
}

export const useProfileStore = defineStore('profile', () => {
  // 自述画像一律从空白开始（刷新即清空，不读任何持久化数据）
  const major = ref('')
  const grade = ref('')
  const skills = ref([])
  const projects = ref([])
  const targetJob = ref('')

  const initialSkills = loadInitialSkills()

  /** 最近一次分析得到的结构化能力表（与上面的自述技能是两回事）。 */
  const lastSkills = ref(initialSkills.skills)
  const lastSkillsAt = ref(initialSkills.at)

  /** 存储写入失败（配额满 / 隐私模式）时置为 true，界面上给一句提示。 */
  const storageFailed = ref(false)

  const hasSelfReportedSkills = computed(() => skills.value.length > 0)
  const hasLastSkills = computed(() => lastSkills.value.length > 0)

  /** 后端 AnalyzeRequest.target_job 要求 minLength 1 —— 这是硬性前置。 */
  const canAnalyze = computed(() => targetJob.value.trim().length > 0)

  /** 非阻塞提示：画像太空时分析仍可跑，但结果质量会差。 */
  const profileWarnings = computed(() => {
    const warnings = []
    if (!major.value.trim()) warnings.push('未填写专业')
    if (!grade.value.trim()) warnings.push('未填写年级')
    if (!skills.value.length) warnings.push('未填写自述技能')
    return warnings
  })

  function persistSkills() {
    storageFailed.value = !writeJson(LAST_SKILLS_KEY, {
      skills: lastSkills.value,
      at: lastSkillsAt.value,
    })
  }

  /** 分析成功后由 analysis store 调用。 */
  function setLastSkills(list, at = new Date().toISOString()) {
    lastSkills.value = Array.isArray(list) ? list.filter((item) => item && item.skill) : []
    lastSkillsAt.value = at
    persistSkills()
  }

  /** 提交给后端的 UserProfileRequest（四字段，与 backend/schemas.py 一一对应）。 */
  function toRequestProfile() {
    return {
      major: major.value.trim(),
      grade: grade.value.trim(),
      skills: [...skills.value],
      projects: [...projects.value],
    }
  }

  /** 清空自述画像；**不清**结构化能力表（那是分析产物，删除需用户明确操作）。 */
  function clearProfile() {
    major.value = ''
    grade.value = ''
    skills.value = []
    projects.value = []
    targetJob.value = ''
  }

  function clearLastSkills() {
    lastSkills.value = []
    lastSkillsAt.value = null
    persistSkills()
  }

  // 分析产物落盘，刷新页面不丢；自述画像**有意不持久化**（见文件头说明）。
  watch(lastSkills, persistSkills, { deep: true })

  return {
    major,
    grade,
    skills,
    projects,
    targetJob,
    lastSkills,
    lastSkillsAt,
    storageFailed,
    hasSelfReportedSkills,
    hasLastSkills,
    canAnalyze,
    profileWarnings,
    setLastSkills,
    toRequestProfile,
    clearProfile,
    clearLastSkills,
  }
})
