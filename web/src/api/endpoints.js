/**
 * 后端接口的一对一封装。
 * 请求体字段严格对应 backend/schemas.py，不自行发明字段。
 */

import { api } from './client'

// ── 认证 ──────────────────────────────────────────────────────────────

/** `POST /api/auth/register` → 201 {token, token_type, user} */
export const register = (body) => api.post('/auth/register', body)

/** `POST /api/auth/login` → {token, token_type, user}；401 用户名或密码错误 */
export const login = (body) => api.post('/auth/login', body)

/** `GET /api/auth/me` → {id, username, created_at}（需 Bearer token） */
export const getMe = (options) => api.get('/auth/me', options)

/** `POST /api/auth/logout` → {ok:true}。JWT 无状态，退出以前端丢弃 token 为准 */
export const logout = () => api.post('/auth/logout')

/** `GET /api/health` → {status, ollama, index, knowledge, stores, config} */
export const getHealth = (options) => api.get('/health', options)

/**
 * `POST /api/analyze` → 202 {status: "queued", run_id, kind: "analyze"}
 *
 * 请求体（AnalyzeRequest，user_profile 与 target_job 必填）：
 *   user_profile : {major, grade, skills: string[], projects: string[]}
 *   target_job   : string（minLength 1）
 *   jd_text      : string | null（可省）—— 用户当场粘贴的招聘要求原文，本次岗位要求的唯一依据。
 *                  上限 config.JD_TEXT_MAX_CHARS（6000 字），超长会 422，前端已提前拦住。
 *                  不传时岗位要求全由模型推断，前端整栏标灰并**不给**匹配度百分比。
 *   growth_events: object[]（可省）—— ⚠️ 分析链路是只读的，绝不在这里传成长事件
 */
export const startAnalyze = (payload) => api.post('/analyze', payload)

/**
 * `POST /api/analyze-and-save` → 202 {status:"queued", run_id, kind:"analyze_and_save"}
 *
 * 与 startAnalyze 同请求体，但在**首次**时会把分析产出的学习/项目计划存为
 * 第 1 轮任务，翻开「学习与项目」页即可看到。已有轮次时保持只读语义。
 */
export const startAnalyzeAndSave = (payload) => api.post('/analyze-and-save', payload)

/**
 * `GET /api/runs/{run_id}` → 运行记录
 *   {run_id, kind, status: queued|running|succeeded|failed,
 *    result, error, created_at, started_at, finished_at}
 * 未知 run_id → 404。
 */
export const getRun = (runId, options) => api.get(`/runs/${encodeURIComponent(runId)}`, options)

// ── 任务 / 成长闭环 ────────────────────────────────────────────────────

/**
 * `GET /api/tasks?round_no=&status=` →
 *   {store_status, writable, warning,
 *    rounds:[{round,target_job,created_at,task_count,completed_count}],
 *    latest_round:{round,created_at,target_job,learning_plan[],project_plan[],tasks[]},
 *    tasks:[{task_id,kind,round,index,title,skills[],status,created_at,completed_at,evidence}],
 *    summary:{total,completed,pending}}
 *
 * 注意：learning_plan / project_plan 的**明细只在 latest_round 里**；
 * rounds[] 只有计数，旧轮次拿不到计划全文（后端未提供该接口）。
 */
export const listTasks = (params = {}, options) => {
  const query = new URLSearchParams()
  if (params.roundNo !== undefined && params.roundNo !== null) query.set('round_no', String(params.roundNo))
  if (params.status) query.set('status', params.status)
  const suffix = query.toString()
  return api.get(`/tasks${suffix ? `?${suffix}` : ''}`, options)
}

/**
 * `POST /api/tasks/{task_id}/complete` → 200（任务不存在 404 / ID 非法 422）
 *
 * 请求体：{ evidence: string(1~5000, 首尾空白会被拒),
 *          profile_skills?: [{skill,level,evidence}] }  ← 传了它，预览才与 growth_node 同基线
 *
 * 返回体同时包含三件事，**必须分开解读**：
 *   ① 任务完成记录 completion_status / completion_written / already_completed
 *   ② 成长成果     growth_event / growth_event_status
 *   ③ 升级预览     growth_evaluated / growth_outcome / upgraded / updates / blocked
 * ③ 只是**预览**：本接口绝不写 runs/growth.json。
 */
export const completeTask = (taskId, body) =>
  api.post(`/tasks/${encodeURIComponent(taskId)}/complete`, body)

/**
 * `POST /api/tasks/clear` →
 *   {status, rounds_removed, tasks_removed, backup, pending_events, warning}
 *
 * status 三种：`cleared`（已清空）/ `needs_confirmation`（有成果还没进成长历史，
 * 什么都没动）/ `refused`（清单文件不能安全写，什么都没动）。
 *
 * 只重置任务清单，**成长历史一行都不动**。清空前一定先把原文件备份，
 * `backup` 就是备份名，照着它能还原。
 * 只有带着 `dropPendingEvents: true` 才会把还没记账的成果一起丢掉。
 */
export const clearTasks = (dropPendingEvents = false) =>
  api.post('/tasks/clear', { drop_pending_events: dropPendingEvents })

/**
 * `GET /api/growth/pending` →
 *   {events:[{type,title,skills[],evidence,at}],
 *    tasks:[{task_id,title,fingerprint}],
 *    skipped[], warnings[], seen, restored}
 *
 * `restored === false` 表示成长历史不可读、**无法判断哪些已处理**，此时 events 一定是空数组 ——
 * 这是"判不了"，不是"没有待办"。
 */
export const getPending = (options) => api.get('/growth/pending', options)

/**
 * `POST /api/growth/manual-event` → {added: true, round, task_id, task}
 * 失败（422）→ {detail: {added:false, reason}}
 *
 * 请求体：{kind: "learning"|"project", title, skills: string[], evidence,
 *          target_job?: string}
 * 用于打破空系统死锁：尚无任务时也可手动补录一条成果。
 */
export const addManualEvent = (body) => api.post('/growth/manual-event', body)

/**
 * `GET /api/growth/history` →
 *   {status, writable, warning, path,
 *    history:[{at, events[], user_skills_before[], user_skills_after[],
 *              level_changes[], blocked_upgrades[], skipped[], invalid_events[],
 *              knowledge_base_status, target_job}],
 *    latest_skills:[{skill,level}], baseline:{source,at,user_skills[]}, confirmed_count}
 */
export const getGrowthHistory = (options) => api.get('/growth/history', options)

/**
 * `POST /api/growth/next-round` → **202** {status:"queued", run_id, kind:"next_round"}
 *
 * ⚠️ 这是全系统**唯一**会写 runs/growth.json 的接口，且会重跑整条流水线（多次本地模型推理）。
 *    调用前必须二次确认；`user_profile` 缺失会让 profile 节点报错、该次 run 变为 failed。
 *
 * 结果用 `GET /api/runs/{run_id}` 查；`result` 有两种形状（无待办时会早退，
 * 不带 target_job / user_skills / growth_diff / learning_plan / project_plan 等字段）。
 *
 * 可带 `jd_text`（含义同 startAnalyze）：下一轮沿用分析页粘过的那份原文，用户不必重粘。
 * 原文只跟着请求走，**不写进 runs/loop.json**。
 */
export const startNextRound = (body) => api.post('/growth/next-round', body)