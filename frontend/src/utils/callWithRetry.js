/** Retry async fn on transient failures (e.g. auth refresh race on first paint). */
export async function callWithRetry(fn, { attempts = 3, delayMs = 350 } = {}) {
  let lastError
  for (let i = 0; i < attempts; i += 1) {
    try {
      return await fn()
    } catch (err) {
      lastError = err
      if (i < attempts - 1) {
        await new Promise((resolve) => {
          setTimeout(resolve, delayMs * (i + 1))
        })
      }
    }
  }
  throw lastError
}
