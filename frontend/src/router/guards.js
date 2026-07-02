import { APP_NAME } from '@/config/app'
import { useAuthStore } from '@/stores/auth'

export function setupRouterGuards(router) {
  router.beforeEach(async (to) => {
    const auth = useAuthStore()

    document.title = to.meta.title
      ? `${to.meta.title} - ${APP_NAME}`
      : APP_NAME

    if (to.meta.public) {
      if (auth.isAuthenticated && to.name === 'login') {
        return { name: 'home' }
      }
      return true
    }

    if (!auth.isAuthenticated) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }

    if (to.meta.adminOnly && !auth.isAdmin) {
      return { name: 'home' }
    }

    if (!auth.user) {
      try {
        await auth.fetchMe()
      } catch {
        auth.logout()
        return { name: 'login', query: { redirect: to.fullPath } }
      }
    }

    return true
  })
}

export async function bootstrapAuth() {
  const auth = useAuthStore()
  if (auth.isAuthenticated && !auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      auth.clearSession()
    }
  }
}
