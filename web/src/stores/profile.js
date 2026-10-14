/**
 * 用户画像（localStorage）。
 *
 * 后端**没有画像接口** —— 画像由前端保存、每次分析随请求提交。
 * 这里维护两个语义不同的东西，**分开存**（不要合并成一个键）：
 *
 *   1. 自述信息 `{major, grade, skills: string[], projects: string[]}`
 *      → 就是后端 `UserProfileRequest` 的四个字段，用户自己填的。
 *   2. 最近一次分析返回的**结构化能力表** `[{skill, level, evidence}]`
 *      → 用户填不出来，只能由分析产生。提交任务完成时当 `profile_skills` 回传，
 *        让"升级预览"和下一轮 growth_node 用同一基线（见 backend/schemas.py 的说明）。
 */

import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { LAST_SKILLS_KEY, PROFILE_KEY, readJson, removeKey, writeJson } from '../utils/storage'

function loadInitialProfile() {
  const saved = readJson(PROFILE_KEY, null)
  return {
    major: typeof saved?.major === 'string' ? saved.major : '',
    grade: typeof saved?.grade === 'string' ? saved.grade : '',
    skills: Array.isArray(saved?.skills) ? saved.skills.filter((s) => typeof s === 'string') : [],
    projects: Array.isArray(saved?.projects) ? saved.projects.filter((s) => typeof s === 'string') : [],
    targetJob: typeof saved?.target_job === 'string' ? saved.target_job : '',
  }
}

function loadInitialSkills() {
  const saved = readJson(LAST_SKILLS_KEY, null)
  if (!saved || typeof saved !== 'object') return { skills: [], at: null }
  return {
    skills: Array.isArray(saved.skills) ? saved.skills : [],
    at: typeof saved.at === 'string' ? saved.at : null,
  }
}

export const useProfileStore = defineStore('profile', () => {
  const initial = loadInitialProfile()
  const initialSkills = loadInitialSkills()

  const major = ref(initial.major)
  const grade = ref(initial.grade)
  const skills = ref(initial.skills)
  const projects = ref(initial.projects)
  const targetJob = ref(initial.targetJob)

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

  function persistProfile() {
    storageFailed.value = !writeJson(PROFILE_KEY, {
      major: major.value,
      grade: grade.value,
      skills: skills.value,
      projects: projects.value,
      target_job: targetJob.value,
    })
  }

  function persistSkills() {
    storageFailed.value = !writeJson(LAST_SKILLS_KEY, {
      skills: lastSkills.value,
      at: lastSkillsAt.value,
    })
  }

  // 任一字段变化即落盘，刷新页面不丢。
  watch([major, grade, skills, projects, targetJob], persistProfile, { deep: true })

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
    removeKey(PROFILE_KEY)
  }

  function clearLastSkills() {
    lastSkills.value = []
    lastSkillsAt.value = null
    removeKey(LAST_SKILLS_KEY)
  }

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
