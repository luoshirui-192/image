import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import {
  cancelBlobSimulatedExportJobApi,
  getBlobSimulatedExportJobApi,
  listBlobSimulatedExportJobsApi,
  pauseBlobSimulatedExportJobApi,
  resumeBlobSimulatedExportJobApi,
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
  const loadingList = ref(false)
  let pollTimer = null

  const activeJobs = computed(() =>
    jobs.value.filter((j) => ['pending', 'running', 'paused'].includes(j.status)),
  )
  const visibleJobs = computed(() =>
    [...jobs.value]
      .filter((j) => !j._dismissed)
      .sort((a, b) => Number(b.id) - Number(a.id)),
  )
  const hasVisible = computed(() => visibleJobs.value.length > 0)

  function upsertJob(job) {
    if (!job?.id) return
    const idx = jobs.value.findIndex((j) => j.id === job.id)
    const prev = idx >= 0 ? jobs.value[idx] : {}
    const next = { ...prev, ...job, _dismissed: false }
    if (idx >= 0) jobs.value[idx] = next
    else jobs.value.unshift(next)
    persistIds(jobs.value.map((j) => j.id))
  }

  function dismissJob(jobId) {
    const idx = jobs.value.findIndex((j) => j.id === jobId)
    if (idx < 0) return
    const job = jobs.value[idx]
    if (['pending', 'running', 'paused'].includes(job.status)) {
      return
    }
    jobs.value.splice(idx, 1)
    persistIds(jobs.value.map((j) => j.id))
    if (!activeJobs.value.length) stopPolling()
  }

  function clearFinished() {
    jobs.value = jobs.value.filter((j) =>
      ['pending', 'running', 'paused'].includes(j.status),
    )
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
    } else if (wasActive && job.status === 'paused') {
      ElMessage.info(job.message || `导出任务 #${jobId} 已暂停`)
    }
    return job
  }

  /** Pull active (+ recent) jobs from server so UI matches DB even after refresh/other clients. */
  async function syncFromServer() {
    loadingList.value = true
    try {
      const res = await listBlobSimulatedExportJobsApi({ activeOnly: false, limit: 30 })
      const list = Array.isArray(res?.data) ? res.data : []
      for (const job of list) {
        if (!job?.id) continue
        // Keep finished jobs only if already tracked, or if still active/paused.
        const active = ['pending', 'running', 'paused'].includes(job.status)
        const known = jobs.value.some((j) => j.id === job.id)
        if (active || known) upsertJob(job)
      }
      // Also ensure any session ids not in list get refreshed.
      const listedIds = new Set(list.map((j) => j.id))
      for (const id of loadPersistedIds()) {
        if (!listedIds.has(id)) {
          try {
            await refreshJob(id)
          } catch {
            // drop
          }
        }
      }
      if (activeJobs.value.length) startPolling()
    } catch {
      // ignore list errors; session restore may still work
    } finally {
      loadingList.value = false
    }
  }

  async function pollAll() {
    // Prefer a cheap list of active jobs so we discover server-side workers (unstick/sidecar).
    try {
      const res = await listBlobSimulatedExportJobsApi({ activeOnly: true, limit: 50 })
      const list = Array.isArray(res?.data) ? res.data : []
      const seen = new Set()
      for (const job of list) {
        if (!job?.id) continue
        seen.add(job.id)
        upsertJob(job)
      }
      // Refresh any locally tracked active ids missing from list (race).
      for (const j of jobs.value) {
        if (['pending', 'running', 'paused'].includes(j.status) && !seen.has(j.id)) {
          try {
            await refreshJob(j.id)
          } catch {
            // ignore
          }
        }
      }
    } catch {
      const ids = jobs.value
        .filter((j) => ['pending', 'running', 'paused'].includes(j.status))
        .map((j) => j.id)
      await Promise.all(
        ids.map(async (id) => {
          try {
            await refreshJob(id)
          } catch {
            // ignore
          }
        }),
      )
    }
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
      ElMessage.success(`导出已加入队列（任务 #${job.id}），可到「迁移任务台」查看进度`)
    }
    void pollAll()
    startPolling()
  }

  async function cancelJob(jobId) {
    await cancelBlobSimulatedExportJobApi(jobId)
    await refreshJob(jobId)
    ElMessage.info(`已请求取消导出 #${jobId}`)
  }

  async function pauseJob(jobId) {
    await pauseBlobSimulatedExportJobApi(jobId)
    await refreshJob(jobId)
    startPolling()
    ElMessage.info(`已请求暂停导出 #${jobId}`)
  }

  async function resumeJob(jobId) {
    await resumeBlobSimulatedExportJobApi(jobId)
    await refreshJob(jobId)
    startPolling()
    ElMessage.success(`导出 #${jobId} 已重新排队`)
  }

  /** Resume tracking after page reload / layout mount — prefer server list. */
  async function restoreFromSession() {
    await syncFromServer()
    const ids = loadPersistedIds()
    await Promise.all(
      ids.map(async (id) => {
        if (jobs.value.some((j) => j.id === id)) return
        try {
          const res = await getBlobSimulatedExportJobApi(id)
          const job = res?.data
          if (job?.id) upsertJob(job)
        } catch {
          // drop missing jobs
        }
      }),
    )
    if (activeJobs.value.length) startPolling()
  }

  return {
    jobs,
    loadingList,
    activeJobs,
    visibleJobs,
    hasVisible,
    trackJob,
    dismissJob,
    clearFinished,
    cancelJob,
    pauseJob,
    resumeJob,
    restoreFromSession,
    syncFromServer,
    refreshJob,
    startPolling,
    stopPolling,
  }
})
