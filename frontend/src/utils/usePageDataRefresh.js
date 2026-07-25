import { onMounted, onUnmounted } from 'vue'

/**
 * Keep page data fresh: load on mount, retry while empty, refresh when tab is visible again.
 *
 * Concurrent refreshes are coalesced (never silently dropped). Visibility refreshes are
 * debounced so rapid alt-tab / multi-window focus does not stampede loaders.
 *
 * @param {() => Promise<void>|void} refreshFn
 * @param {{
 *   isEmpty?: () => boolean,
 *   intervalMs?: number,
 *   maxEmptyRetries?: number,
 *   refreshOnVisible?: boolean,
 *   alwaysRefreshOnVisible?: boolean,
 *   visibleDebounceMs?: number,
 * }} [options]
 */
export function usePageDataRefresh(refreshFn, options = {}) {
  const {
    isEmpty = () => false,
    intervalMs = 2500,
    maxEmptyRetries = 12,
    refreshOnVisible = true,
    // Prefer refreshing when empty; full reload on every focus is opt-in per page.
    alwaysRefreshOnVisible = false,
    visibleDebounceMs = 350,
  } = options

  let timer = null
  let emptyTries = 0
  let running = false
  let pending = false
  let visibleTimer = null
  let disposed = false

  async function runRefresh({ force = false } = {}) {
    if (disposed) return false
    if (running) {
      pending = true
      return false
    }
    running = true
    let ran = true
    try {
      await refreshFn({ force })
    } catch {
      // callers handle errors; keep retrying while empty
    } finally {
      running = false
      if (pending && !disposed) {
        pending = false
        // Chain one follow-up so a visibility refresh during an in-flight load is not lost.
        void runRefresh({ force: true })
      }
    }
    return ran
  }

  function stopEmptyPoll() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function startEmptyPoll() {
    stopEmptyPoll()
    emptyTries = 0
    timer = setInterval(async () => {
      if (disposed) {
        stopEmptyPoll()
        return
      }
      if (!isEmpty()) {
        stopEmptyPoll()
        return
      }
      if (running) {
        // Wait for in-flight work; do not burn retry budget on no-ops.
        pending = true
        return
      }
      emptyTries += 1
      if (emptyTries > maxEmptyRetries) {
        stopEmptyPoll()
        return
      }
      const ran = await runRefresh({ force: true })
      if (ran && !isEmpty()) stopEmptyPoll()
    }, intervalMs)
  }

  function scheduleVisibleRefresh() {
    if (!refreshOnVisible) return
    if (document.visibilityState !== 'visible') return
    if (!alwaysRefreshOnVisible && !isEmpty()) return
    if (visibleTimer) clearTimeout(visibleTimer)
    visibleTimer = setTimeout(() => {
      visibleTimer = null
      if (disposed || document.visibilityState !== 'visible') return
      if (!alwaysRefreshOnVisible && !isEmpty()) return
      void runRefresh({ force: true }).then(() => {
        if (isEmpty()) startEmptyPoll()
      })
    }, visibleDebounceMs)
  }

  function onVisibility() {
    scheduleVisibleRefresh()
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onVisibility)
    void runRefresh({ force: true }).then(() => {
      if (isEmpty()) startEmptyPoll()
    })
  })

  onUnmounted(() => {
    disposed = true
    document.removeEventListener('visibilitychange', onVisibility)
    stopEmptyPoll()
    if (visibleTimer) {
      clearTimeout(visibleTimer)
      visibleTimer = null
    }
  })

  return {
    refreshNow: () => runRefresh({ force: true }),
    startEmptyPoll,
    stopEmptyPoll,
  }
}
