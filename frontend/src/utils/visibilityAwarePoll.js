/**
 * Interval that only runs while the document is visible.
 * Stops when the tab/window is hidden so minimize / background tabs
 * do not keep the main thread busy with polling work.
 *
 * @param {() => void} tick
 * @param {number} intervalMs
 * @returns {{ restart: () => void, stop: () => void, isRunning: () => boolean }}
 */
export function createVisibilityAwarePoll(tick, intervalMs) {
  let timer = null
  let disposed = false

  function clear() {
    if (timer != null) {
      clearInterval(timer)
      timer = null
    }
  }

  function isHidden() {
    return typeof document !== 'undefined' && document.visibilityState === 'hidden'
  }

  function arm() {
    clear()
    if (disposed || isHidden()) return
    timer = setInterval(() => {
      if (isHidden()) {
        clear()
        return
      }
      tick()
    }, intervalMs)
  }

  function onVisibility() {
    if (disposed) return
    if (document.visibilityState === 'visible') {
      tick()
      arm()
    } else {
      clear()
    }
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibility)
  }
  if (!isHidden()) {
    tick()
    arm()
  }

  return {
    restart: arm,
    stop() {
      disposed = true
      clear()
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisibility)
      }
    },
    isRunning: () => timer != null,
  }
}
