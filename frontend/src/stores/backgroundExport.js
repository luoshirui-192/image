import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import {
  cancelBlobSimulatedExportJobApi,
  getBlobSimulatedExportJobApi,
} from '@/api/images'

const STORAGE_KEY = 'image_db_bg_export_jobs'

function loadPersistedIds() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list.map(Number).filter((n) => n > 0) : []
  } catch {
    return []
  }
}

function persistIds(ids) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...new Set(ids)]))
}

export const useBackgroundExportStore = defineStore('backgroundExport', () => {
  /** @type {import('vue').Ref<Array<Record<string, any>>>} */
  const jobs = ref([])
  let pollTimer = null

  const activeJobs = computed(() =>
    jobs.value.filter((j) => ['pending', 'running'].includes(j.status)),
  )
  const visibleJobs = computed(() => jobs.value.filter((j) => !j._dismissed))
  const hasVisible = computed(() => visibleJobs.value.length > 0)

  function upsertJob(job) {
    if (!job?.id) return
    const idx = jobs.value.findIndex((j) => j.id === job.id)
    const next = { ...(idx >= 0 ? jobs.value[idx] : {}), ...job, _dismissed: false }
    if (idx >= 0) jobs.value[idx] = next
    else jobs.value.unshift(next)
    persistIds(jobs.value.map((j) => j.id))
  }

  function dismissJob(jobId) {
    const idx = jobs.value.findIndex((j) => j.id === jobId)
    if (idx < 0) return
    const job = jobs.value[idx]
    if (['pending', 'running'].includes(job.status)) {
      // Keep tracking but hide from dock? Better: don't dismiss active — cancel first.
      return
    }
    jobs.value.splice(idx, 1)
    persistIds(jobs.value.map((j) => j.id))
    if (!activeJobs.value.length) stopPolling()
  }

  function clearFinished() {
    jobs.value = jobs.value.filter((j) => ['pending', 'running'].includes(j.status))
    persistIds(jobs.value.map((j) => j.id))
  }

  async function refreshJob(jobId) {
    const res = await getBlobSimulatedExportJobApi(jobId)
    const job = res?.data
    if (!job || typeof job !== 'object') return null
    const prev = jobs.value.find((j) => j.id === jobId)
    const wasActive = prev && ['pending', 'running'].includes(prev.status)
    upsertJob(job)
    if (wasActive && job.status === 'completed') {
      ElMessage.success(job.message || `导出任务 #${jobId} 已完成`)
    } else if (wasActive && job.status === 'failed') {
      ElMessage.error(job.message || job.last_error || `导出任务 #${jobId} 失败`)
    } else if (wasActive && job.status === 'cancelled') {
      ElMessage.warning(job.message || `导出任务 #${jobId} 已取消`)
    }
    return job
  }

  async function pollAll() {
    const ids = jobs.value
      .filter((j) => ['pending', 'running'].includes(j.status))
      .map((j) => j.id)
    if (!ids.length) {
      stopPolling()
      return
    }
    await Promise.all(
      ids.map(async (id) => {
        try {
          await refreshJob(id)
        } catch {
          // ignore transient poll errors
        }
      }),
    )
    if (!activeJobs.value.length) stopPolling()
  }

  function startPolling() {
    if (pollTimer) return
    pollTimer = setInterval(() => {
      void pollAll()
    }, 1500)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /** Call after starting an export job from any page. */
  function trackJob(job, { notify = true } = {}) {
    if (!job?.id) return
    upsertJob(job)
    if (notify) {
      ElMessage.success(`导出已在后台运行（任务 #${job.id}），可继续其他操作`)
    }
    void pollAll()
    startPolling()
  }

  async function cancelJob(jobId) {
    await cancelBlobSimulatedExportJobApi(jobId)
    await refreshJob(jobId)
    ElMessage.info(`已请求取消导出 #${jobId}`)
  }

  /** Resume tracking after page reload / layout mount. */
  async function restoreFromSession() {
    const ids = loadPersistedIds()
    if (!ids.length) return
    await Promise.all(
      ids.map(async (id) => {
        try {
          const res = await getBlobSimulatedExportJobApi(id)
          const job = res?.data
          if (job?.id) upsertJob(job)
        } catch {
          // drop missing jobs
        }
      }),
    )
    // Drop ancient finished jobs older than keep — keep recent finished for dock
    if (activeJobs.value.length) startPolling()
  }

  return {
    jobs,
    activeJobs,
    visibleJobs,
    hasVisible,
    trackJob,
    dismissJob,
    clearFinished,
    cancelJob,
    restoreFromSession,
    refreshJob,
    startPolling,
    stopPolling,
  }
})
