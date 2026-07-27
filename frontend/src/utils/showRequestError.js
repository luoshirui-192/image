import { ElMessage } from 'element-plus'

/**
 * Show an API error toast once.
 * Axios interceptor already toasts HTTP failures and sets err.__globalToastShown.
 * Use this in catch blocks instead of ElMessage.error(err.message) to avoid double toasts.
 */
export function showRequestError(err, fallback = '请求失败') {
  if (err?.__globalToastShown) return
  const msg = err?.message || fallback
  if (!msg) return
  ElMessage.error(msg)
}
