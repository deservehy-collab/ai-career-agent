/**
 * 系统状态（`GET /api/health`）。
 * 返回结构见 backend/services.py 的 health()：
 *   {status: "ok"|"degraded", ollama{...}, index{...}, knowledge{...}, stores{...}, config{...}}
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { getHealth } from '../api/endpoints'

export const useHealthStore = defineStore('health', () => {
  const data = ref(null)
  const loading = ref(false)
  const errorMessage = ref('')
  const fetchedAt = ref(null)

  const status = computed(() => data.value?.status ?? 'unknown')
  const isOk = computed(() => status.value === 'ok')
  /** 后端连不上时 data 为 null，要和"后端说 degraded"区分开。 */
  const unreachable = computed(() => !data.value && !!errorMessage.value)

  async function refresh() {
    loading.value = true
    errorMessage.value = ''
    try {
      data.value = await getHealth()
      fetchedAt.value = new Date().toISOString()
    } catch (error) {
      data.value = null
      errorMessage.value = error?.message || '获取系统状态失败'
    } finally {
      loading.value = false
    }
  }

  return { data, loading, errorMessage, fetchedAt, status, isOk, unreachable, refresh }
})
