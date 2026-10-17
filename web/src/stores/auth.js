/**
 * 登录态（JWT）。
 *
 * token 存 localStorage（client.js 直接读同一份，避免在请求层绕进 pinia）；
 * user 只用于界面展示，进入受保护页面前由路由守卫调 fetchMe() 对 token
 * 做一次真实性校验，verified 标记"本次会话已确认有效"。
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { getMe, login as loginRequest, register as registerRequest } from '../api/endpoints'
import {
  clearAuthStorage, getAuthToken, getStoredUser, setAuthToken, setStoredUser,
} from '../utils/storage'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getAuthToken())
  const user = ref(getStoredUser())
  const verified = ref(false)
  const loading = ref(false)

  const isLoggedIn = computed(() => !!token.value)

  function adopt(response) {
    token.value = response.token
    user.value = response.user
    verified.value = true
    setAuthToken(response.token)
    setStoredUser(response.user)
  }

  function logout() {
    token.value = null
    user.value = null
    verified.value = false
    clearAuthStorage()
  }

  async function login(username, password) {
    loading.value = true
    try {
      adopt(await loginRequest({ username, password }))
    } finally {
      loading.value = false
    }
  }

  /** 注册成功后端直接发 token：注册即登录，不用再输一次密码。 */
  async function register(username, password) {
    loading.value = true
    try {
      adopt(await registerRequest({ username, password }))
    } finally {
      loading.value = false
    }
  }

  async function fetchMe() {
    const data = await getMe()
    user.value = data
    verified.value = true
    setStoredUser(data)
  }

  return { token, user, verified, loading, isLoggedIn, login, register, logout, fetchMe }
})
