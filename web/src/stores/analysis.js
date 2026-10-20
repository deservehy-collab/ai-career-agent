/**
 * 岗位分析：发起 → 轮询 → 保存结果。
 *
 * 协议（backend/app.py）：
 *   POST /api/analyze-and-save → 202 {status:"queued", run_id, kind:"analyze_and_save"}
 *   GET  /api/runs/{run_id} → {status: queued|running|succeeded|failed, result, error, ...}
 *
 * ⚠️ 分析不再走只读 /api/analyze，而是走 /api/analyze-and-save：
 * 首次分析会顺手把产出的学习/项目计划存成第 1 轮任务（根治冷启动死锁）。
 * 因此 `result` 是**带包装的**：分析结果在 `result.analysis` 里，外层是 round_created /
 * warning 这些建轮次元信息。本 store 对外暴露的 `result` 已解包成投影结果本身，
 * 视图层按扁平字段读即可（见 applySuccess）。
 *
 * ⚠️ 绝不传 growth_events
 * ---------------------------------------
 * 分析链路的成长存储被隔离到临时目录（backend/analyze.py 的 _isolated_growth_store），
 * 即使传了成长事件、返回体里也可能写着 history_written=true，**实际上什么都没落盘**。
 * 成长一律走「提交任务完成 → 待处理成果 → 生成下一轮」那条路径，不从这里走。
 *
 * 分析失败时画像不受任何影响：画像在 profile store / localStorage 里，
 * 这里只读不写。
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { ApiError } from '../api/client'
import { getRun, startAnalyzeAndSave } from '../api/endpoints'
import { pollRun, RUN_STATUS } from '../composables/useRunPolling'
import { formatRunError } from '../utils/format'
import { useProfileStore } from './profile'

/** 界面用的状态机：idle 之外都直接映射后端四态。 */
export const ANALYSIS_STATUS = {
  IDLE: 'idle',
  QUEUED: RUN_STATUS.QUEUED,
  RUNNING: RUN_STATUS.RUNNING,
  SUCCEEDED: RUN_STATUS.SUCCEEDED,
  FAILED: RUN_STATUS.FAILED,
}

export const useAnalysisStore = defineStore('analysis', () => {
  const runId = ref(null)
  const status = ref(ANALYSIS_STATUS.IDLE)
  const result = ref(null)
  const errorMessage = ref('')
  const errorKind = ref(null) // network | notfound | timeout | run_failed | http | null
  const startedAt = ref(null)
  const finishedAt = ref(null)

  // 本次分析的目标岗位，用于结果区标题
  const targetJob = ref('')

  let controller = null

  const isRunning = computed(
    () => status.value === ANALYSIS_STATUS.QUEUED || status.value === ANALYSIS_STATUS.RUNNING,
  )
  const hasResult = computed(() => !!result.value)
  const lastError = computed(() => errorMessage.value)

  /** 后端汇总方案（final_plan 由 build_final_plan 现算）。 */
  const finalPlan = computed(() => result.value?.final_plan ?? null)
  /** 岗位匹配结论（build_final_plan 里的 jd_match）。 */
  const jdMatch = computed(() => finalPlan.value?.jd_match ?? null)
  /**
   * 本次岗位要求的主依据：user_pasted | model_only（backend/analyze.py）。
   * 旧结果里没有这个键时按"有没有粘原文"推断，不让界面因为缺字段显示"-"。
   */
  const requirementBasis = computed(() => {
    const raw = result.value?.requirement_basis
    if (raw) return raw
    return result.value?.user_jd_provided ? 'user_pasted' : 'model_only'
  })


  /** 事后查询一次运行记录（不轮询），用于"稍后再查"。 */
  async function fetchOnce(id = runId.value) {
    if (!id) return null
    const record = await getRun(id)
    if (record.status === RUN_STATUS.SUCCEEDED) applySuccess(record)
    else if (record.status === RUN_STATUS.FAILED) applyFailure(record)
    else status.value = record.status
    return record
  }

  function applySuccess(record) {
    status.value = ANALYSIS_STATUS.SUCCEEDED
    // /api/analyze-and-save 把只读分析结果**包在 analysis 里**，外层是建轮次的元信息
    // （round_created / round_no / warning）；只读的 /api/analyze 则直接返回投影结果。
    // 这里必须解包，否则 user_skills / job_requirements / skill_gaps / job_evidence /
    // retrieval_status / growth_diff / final_plan 全都会读成 undefined —— 外层只有
    // learning_plan 与 project_plan 两个副本，所以现象是"学习和项目有、其他全空"。
    const raw = record.result ?? null
    result.value = raw?.analysis ?? raw
    finishedAt.value = record.finished_at || new Date().toISOString()
    errorMessage.value = ''
    errorKind.value = null

    // 保存结构化能力表，供后续"提交任务完成"当 profile_skills 用。
    const profileStore = useProfileStore()
    const skills = result.value?.user_skills
    if (Array.isArray(skills) && skills.length) {
      profileStore.setLastSkills(skills, finishedAt.value)
    }
  }

  function applyFailure(record) {
    status.value = ANALYSIS_STATUS.FAILED
    result.value = null
    finishedAt.value = record.finished_at || new Date().toISOString()
    // 后端把异常消息放在 error 字段（backend/jobs.py 的 TaskRecord），格式是
    // "ValueError: 具体原因"；类名不给使用者看（见 utils/format.js 的 formatRunError）
    errorMessage.value = formatRunError(record.error, '分析任务失败，但后端未给出错误信息。')
    errorKind.value = 'run_failed'
  }

  function describeError(error) {
    if (error instanceof ApiError) {
      if (error.isNetworkError) return { kind: 'network', message: error.message }
      if (error.isNotFound) {
        return {
          kind: 'notfound',
          message:
            '查不到这次运行记录。运行记录保存在后端内存里，若后端重启过就会失效；' +
            '请重新发起分析。',
        }
      }
      if (error.status === 408) return { kind: 'timeout', message: error.message }
      return { kind: 'http', message: error.message }
    }
    if (error?.name === 'AbortError') return null // 主动取消，不算错误
    return { kind: 'http', message: error?.message || '未知错误' }
  }

  /**
   * 发起分析并轮询到终态。
   *
   * @param {object} params
   * @param {object} params.profile    → UserProfileRequest 四字段
   * @param {string} params.targetJob  → AnalyzeRequest.target_job（必填）
   * @param {string} [params.jdText]   → AnalyzeRequest.jd_text：用户粘贴的招聘要求原文
   */
  async function start({ profile, targetJob: job, jdText: pastedJd = '' }) {
    cancel()

    runId.value = null
    status.value = ANALYSIS_STATUS.QUEUED
    result.value = null
    errorMessage.value = ''
    errorKind.value = null
    startedAt.value = new Date().toISOString()
    finishedAt.value = null
    targetJob.value = job

    const pasted = String(pastedJd || '').trim()

    controller = new AbortController()
    const { signal } = controller

    const body = {
      user_profile: profile,
      target_job: job,
      // 不传 growth_events（见文件头说明）
    }
    if (pasted) body.jd_text = pasted

    try {
      const accepted = await startAnalyzeAndSave(body)
      runId.value = accepted.run_id
      status.value = accepted.status || ANALYSIS_STATUS.QUEUED

      const record = await pollRun(accepted.run_id, {
        signal,
        onTick: (tick) => {
          status.value = tick.status
        },
      })

      if (record.status === RUN_STATUS.SUCCEEDED) applySuccess(record)
      else applyFailure(record)
    } catch (error) {
      const described = describeError(error)
      if (!described) {
        // 主动取消：回到未开始，不报错
        status.value = ANALYSIS_STATUS.IDLE
        return
      }
      status.value = ANALYSIS_STATUS.FAILED
      result.value = null
      errorMessage.value = described.message
      errorKind.value = described.kind
      finishedAt.value = new Date().toISOString()
    } finally {
      controller = null
    }
  }

  /** 取消轮询（离开页面 / 重新发起时调用）。后台任务本身不受影响，只是不再等它。 */
  function cancel() {
    if (controller) {
      controller.abort()
      controller = null
    }
  }

  /** 清空本次结果与错误（不影响画像）。 */
  function reset() {
    cancel()
    runId.value = null
    status.value = ANALYSIS_STATUS.IDLE
    result.value = null
    errorMessage.value = ''
    errorKind.value = null
    startedAt.value = null
    finishedAt.value = null
  }

  return {
    runId,
    status,
    result,
    errorMessage,
    errorKind,
    startedAt,
    finishedAt,
    targetJob,
    isRunning,
    hasResult,
    lastError,
    finalPlan,
    jdMatch,
    requirementBasis,
    start,
    cancel,
    reset,
    fetchOnce,
  }
})