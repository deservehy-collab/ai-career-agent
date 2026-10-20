/**
 * HTTP 客户端：统一前缀、JSON 编解码、错误归一。
 *
 * 用浏览器原生 fetch，不引入 axios —— 依赖越少，安装面越小。
 *
 * 错误归一的依据是**后端实际的错误体**（backend/app.py）：
 *   - 422 Pydantic 校验失败 → `{"detail": [{type, loc, msg, input}, ...]}`
 *   - 422 业务参数非法     → `{"detail": "<字符串>"}`（app.py 里 raise HTTPException(detail=str)）
 *   - 404 任务/运行不存在   → `{"detail": "<字符串>"}`（如 "未知的 run_id：xxx"）
 *   - 404 任务不存在        → `{"detail": {task_id, completion_status, reason}}`（dict）
 * 三种形态都要能读成一句人话，否则界面上会冒出 [object Object]。
 */

import { getAuthToken, clearAuthStorage } from '../utils/storage'

const BASE = '/api'

/** 登录态失效后跳转前，避免在登录/注册页原地打转。 */
export function redirectToLogin() {
  const { pathname, search } = window.location
  if (pathname === '/login' || pathname === '/register') return
  const redirect = encodeURIComponent(pathname + search)
  window.location.assign(`/login?redirect=${redirect}`)
}

/** 后端连不上（fetch 直接 reject）时用的状态码，区别于后端返回的 4xx/5xx。 */
export const NETWORK_ERROR_STATUS = 0

export class ApiError extends Error {
  constructor(message, { status = NETWORK_ERROR_STATUS, detail = null, cause = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.cause = cause
  }

  /** 后端进程没起来 / 代理转发失败。 */
  get isNetworkError() {
    return this.status === NETWORK_ERROR_STATUS
  }

  get isNotFound() {
    return this.status === 404
  }

  get isValidationError() {
    return this.status === 422
  }
}

/** 把后端的 detail 折成一句可读文本。 */
export function describeDetail(detail) {
  if (detail == null) return ''
  if (typeof detail === 'string') return detail

  // Pydantic 校验错误数组：[{loc: ['body','evidence'], msg: '...'}]
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === 'object') {
        const where = Array.isArray(item.loc) ? item.loc.filter((p) => p !== 'body').join('.') : ''
        const msg = item.msg || item.type || '校验失败'
        return where ? `${where}：${msg}` : msg
      }
      return String(item)
    })
    return parts.join('；')
  }

  // 业务 dict，例如任务完成的 404：{task_id, completion_status, reason}
  if (typeof detail === 'object') {
    if (detail.reason) return String(detail.reason)
    try {
      return JSON.stringify(detail)
    } catch {
      return '请求失败'
    }
  }

  return String(detail)
}

async function readBody(response) {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const init = { method, headers: {}, signal }

  const token = getAuthToken()
  if (token) init.headers.Authorization = `Bearer ${token}`

  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(`${BASE}${path}`, init)
  } catch (cause) {
    // 被主动取消的请求不要伪装成"后端挂了"
    if (cause && cause.name === 'AbortError') throw cause
    throw new ApiError(
      '连不上后端服务：请先确认后端已经启动，再回来点「重新检查」。',
      { status: NETWORK_ERROR_STATUS, cause },
    )
  }

  const payload = await readBody(response)

  if (!response.ok) {
    // 业务接口的 401 = token 缺失/过期/无效：清掉本地登录态并回登录页。
    // /auth/ 自身的 401（比如密码错误）属于正常业务反馈，不能清登录态。
    if (response.status === 401 && !path.startsWith('/auth/')) {
      clearAuthStorage()
      redirectToLogin()
    }
    const detail = payload && typeof payload === 'object' ? payload.detail : payload
    const described = describeDetail(detail)
    const fallback = {
      404: '资源不存在',
      422: '请求参数不合法',
      500: '后端内部错误',
    }[response.status]
    throw new ApiError(
      described || fallback || `请求失败（HTTP ${response.status}）`,
      { status: response.status, detail },
    )
  }

  return payload
}

export const api = {
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  post: (path, body, options) => request(path, { ...options, method: 'POST', body }),
}
