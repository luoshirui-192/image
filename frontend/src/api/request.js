import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 60000,
})

let refreshing = null
/** Depth counter: while > 0, interceptor skips ElMessage (used by callWithRetry mid-attempts). */
let suppressGlobalErrorDepth = 0

export function beginSuppressGlobalError() {
  suppressGlobalErrorDepth += 1
}

export function endSuppressGlobalError() {
  suppressGlobalErrorDepth = Math.max(0, suppressGlobalErrorDepth - 1)
}

function isAuthTokenUrl(url = '') {
  return /\/auth\/(login|refresh)\/?(\?|$)/.test(String(url))
}

function forceReLogin() {
  const auth = useAuthStore()
  auth.logout()
  if (router.currentRoute.value.name !== 'login') {
    router.push({
      name: 'login',
      query: { redirect: router.currentRoute.value.fullPath },
    })
  }
}

request.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.accessToken) {
    config.headers.Authorization = `Bearer ${auth.accessToken}`
  }
  if (!(config.data instanceof FormData)) {
    config.headers['Content-Type'] = config.headers['Content-Type'] || 'application/json'
  } else {
    delete config.headers['Content-Type']
  }
  return config
})

request.interceptors.response.use(
  (response) => {
    const payload = response.data
    if (payload && typeof payload === 'object' && 'code' in payload) {
      if (payload.code !== 0) {
        const err = new Error(payload.message || '请求失败')
        err.code = payload.code
        err.data = payload.data
        // Business errors: let the caller toast (may be quiet / custom UX).
        return Promise.reject(err)
      }
      return payload
    }
    return payload
  },
  async (error) => {
    const auth = useAuthStore()
    const original = error.config
    const status = error.response?.status

    // Expired / invalid JWT: try one refresh, otherwise clear stale session.
    // Never refresh on login/refresh itself (avoids loops after SECRET_KEY rotate).
    if (status === 401 && original && !isAuthTokenUrl(original.url)) {
      if (auth.refreshToken && !original._retry) {
        original._retry = true
        try {
          refreshing = refreshing || auth.refreshAccessToken()
          await refreshing
          refreshing = null
          original.headers = original.headers || {}
          original.headers.Authorization = `Bearer ${auth.accessToken}`
          return request(original)
        } catch {
          refreshing = null
          forceReLogin()
          return Promise.reject(error)
        }
      }
      // Access present but refresh missing/expired → stuck “logged in” with endless 401s.
      if (auth.accessToken || auth.refreshToken) {
        forceReLogin()
      }
    }

    const message =
      error.response?.data?.message ||
      error.message ||
      '网络请求失败'
    const err = new Error(message)
    err.data = error.response?.data?.data
    err.code = error.response?.data?.code
    if (status !== 401 && !error.config?.skipGlobalError && suppressGlobalErrorDepth === 0) {
      ElMessage.error(message)
      err.__globalToastShown = true
    }
    if (status === 401) {
      err.__globalToastShown = true
    }
    return Promise.reject(err)
  },
)

export default request
