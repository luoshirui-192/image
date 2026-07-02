import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { loginApi, meApi, refreshApi } from '@/api/auth'

const ACCESS_KEY = 'image_db_access'
const REFRESH_KEY = 'image_db_refresh'
const USER_KEY = 'image_db_user'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(localStorage.getItem(ACCESS_KEY) || '')
  const refreshToken = ref(localStorage.getItem(REFRESH_KEY) || '')
  const user = ref(loadUser())

  const isAuthenticated = computed(() => Boolean(accessToken.value))
  const isAdmin = computed(() => user.value?.is_admin === true || user.value?.role === 'admin')
  const username = computed(() => user.value?.username || '')

  function loadUser() {
    try {
      const raw = localStorage.getItem(USER_KEY)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  }

  function persistSession({ access, refresh, user: userData }) {
    accessToken.value = access
    refreshToken.value = refresh
    user.value = userData
    localStorage.setItem(ACCESS_KEY, access)
    localStorage.setItem(REFRESH_KEY, refresh)
    localStorage.setItem(USER_KEY, JSON.stringify(userData))
  }

  function clearSession() {
    accessToken.value = ''
    refreshToken.value = ''
    user.value = null
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(USER_KEY)
  }

  async function login(username, password) {
    const res = await loginApi(username, password)
    persistSession(res.data)
    return res
  }

  async function fetchMe() {
    const res = await meApi()
    user.value = res.data
    localStorage.setItem(USER_KEY, JSON.stringify(res.data))
    return res.data
  }

  async function refreshAccessToken() {
    if (!refreshToken.value) {
      throw new Error('no refresh token')
    }
    const res = await refreshApi(refreshToken.value)
    accessToken.value = res.data.access
    localStorage.setItem(ACCESS_KEY, res.data.access)
    return res.data.access
  }

  function logout() {
    clearSession()
  }

  return {
    accessToken,
    refreshToken,
    user,
    isAuthenticated,
    isAdmin,
    username,
    login,
    fetchMe,
    refreshAccessToken,
    logout,
    clearSession,
  }
})
