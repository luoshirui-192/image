import { onMounted, onUnmounted } from 'vue'

/**
 * Keep page option lists populated: retry while empty and refresh when tab becomes visible.
 * Fixes first-paint / second-page races that leave Element Plus selects showing「无数据」.
 *
 * @param {() => Promise<void>|void} refreshFn
 * @param {{
 *   isEmpty?: () => boolean,
 *   intervalMs?: number,
 *   maxEmptyRetries?: number,
 *   refreshOnVisible?: boolean,
 * }} [options]
 */
export function usePageDataRefresh(refreshFn, options = {}) {
  const {
    isEmpty = () => false,
    intervalMs = 2500,
    maxEmptyRetries = 12,
    refreshOnVisible = true,
  } = options

  let timer = null
  let emptyTries = 0
  let running = false

  async function runRefresh({ force = false } = {}) {
    if (running) return
    running = true
    try {
      await refreshFn({ force })
    } catch {
      // callers handle errors; keep retrying while empty
    } finally {
      running = false
    }
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
      if (!isEmpty()) {
        stopEmptyPoll()
        return
      }
      emptyTries += 1
      if (emptyTries > maxEmptyRetries) {
        stopEmptyPoll()
        return
      }
      await runRefresh({ force: true })
      if (!isEmpty()) stopEmptyPoll()
    }, intervalMs)
  }

  function onVisibility() {
    if (!refreshOnVisible) return
    if (document.visibilityState !== 'visible') return
    if (isEmpty()) {
      void runRefresh({ force: true }).then(() => {
        if (isEmpty()) startEmptyPoll()
      })
    }
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onVisibility)
    void runRefresh({ force: true }).then(() => {
      if (isEmpty()) startEmptyPoll()
    })
  })

  onUnmounted(() => {
    document.removeEventListener('visibilitychange', onVisibility)
    stopEmptyPoll()
  })

  return {
    refreshNow: () => runRefresh({ force: true }),
    startEmptyPoll,
    stopEmptyPoll,
  }
}
