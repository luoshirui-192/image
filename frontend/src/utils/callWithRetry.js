import { beginSuppressGlobalError, endSuppressGlobalError } from '@/api/request'

/** Retry async fn on transient failures (e.g. auth refresh race on first paint). */
export async function callWithRetry(fn, { attempts = 3, delayMs = 350 } = {}) {
  let lastError
  for (let i = 0; i < attempts; i += 1) {
    const isLast = i === attempts - 1
    // Suppress global toast on intermediate failures; final attempt may toast once.
    if (!isLast) beginSuppressGlobalError()
    try {
      return await fn()
    } catch (err) {
      lastError = err
      if (!isLast) {
        await new Promise((resolve) => {
          setTimeout(resolve, delayMs * (i + 1))
        })
      }
    } finally {
      if (!isLast) endSuppressGlobalError()
    }
  }
  throw lastError
}
