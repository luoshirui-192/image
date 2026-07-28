import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import {
  cancelFingerprintImportJobApi,
  fetchFingerprintImportJobApi,
  fetchFingerprintImportJobsApi,
} from '@/api/fingerprints'
import { createVisibilityAwarePoll } from '@/utils/visibilityAwarePoll'

const STORAGE_KEY = 'image_db_fp_import_jobs'
const POLL_MS = 3000
const POLLABLE = ['pending', 'running']

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

function normalizeJob(payload) {
  const data = payload?.data ?? payload
  if (!data || typeof data !== 'object') return null
  if (data.job && typeof data.job === 'object') return data.job
  if (data.id != null || data.status != null) return data
  return null
}

export const useFingerprintImportStore = defineStore('fingerprintImport', () => {
  /** @type {import('vue').Ref<Array<Record<string, any>>>} */
  const jobs = ref([])
  const loadingList = ref(false)
  /** @type {ReturnType<typeof createVisibilityAwarePoll> | null} */
  let pollHandle = null

  const activeJobs = computed(() =>
    jobs.value.filter((j) => POLLABLE.includes(j.status)),
  )
  const visibleJobs = computed(() =>
    [...jobs.value]
      .filter((j) => !j._dismissed)
      .sort((a, b) => Number(b.id) - Number(a.id)),
  )
  const hasVisible = computed(() => visibleJobs.value.length > 0)
  const latestActive = computed(() => activeJobs.value[0] || null)

  function persistTrackedIds() {
    persistIds(jobs.value.filter((j) => POLLABLE.includes(j.status)).map((j) => j.id))
  }

  function upsertJob(job) {
    if (!job?.id) return
    const idx = jobs.value.findIndex((j) => j.id === job.id)
    const prev = idx >= 0 ? jobs.value[idx] : {}
    const next = { ...prev, ...job, _dismissed: false }
    if (idx >= 0) jobs.value[idx] = next
    else jobs.value.unshift(next)
    persistTrackedIds()
  }

  function dismissJob(jobId) {
    const idx = jobs.value.findIndex((j) => j.id === jobId)
    if (idx < 0) return
    const job = jobs.value[idx]
    if (POLLABLE.includes(job.status)) return
    jobs.value.splice(idx, 1)
    persistTrackedIds()
    if (!activeJobs.value.length) stopPolling()
  }

  function clearFinished() {
    jobs.value = jobs.value.filter((j) => POLLABLE.includes(j.status))
    persistTrackedIds()
  }

  async function refreshJob(jobId) {
    const res = await fetchFingerprintImportJobApi(jobId)
    const job = normalizeJob(res)
    if (!job || typeof job !== 'object') return null
    const prev = jobs.value.find((j) => j.id === jobId)
    const wasActive = prev && POLLABLE.includes(prev.status)
    upsertJob(job)
    if (wasActive && job.status === 'completed') {
      const dupTotal = Number(job.duplicate_report?.total || 0)
      const wbFail = Number(job.writeback_failed || 0)
      if (job.path_writeback_enabled && wbFail > 0) {
        ElMessage.warning(job.message || `导入 #${jobId} 完成，路径写回有失败`)
      } else if (dupTotal > 0) {
        ElMessage.warning(job.message || `导入 #${jobId} 完成，发现 ${dupTotal} 项重复`)
      } else {
        ElMessage.success(job.message || `导入任务 #${jobId} 已完成`)
      }
    } else if (wasActive && job.status === 'failed') {
      ElMessage.error(job.message || job.last_error || `导入任务 #${jobId} 失败`)
    } else if (wasActive && job.status === 'cancelled') {
      ElMessage.warning(job.message || `导入任务 #${jobId} 已取消`)
    }
    return job
  }

  async function syncFromServer() {
    loadingList.value = true
    try {
      const res = await fetchFingerprintImportJobsApi({ limit: 30 })
      const payload = res?.data
      const list = Array.isArray(payload?.items)
        ? payload.items
        : Array.isArray(payload)
          ? payload
          : []
      for (const job of list) {
        if (!job?.id) continue
        const active = POLLABLE.includes(job.status)
        const known = jobs.value.some((j) => j.id === job.id)
        if (active || known) upsertJob(job)
      }
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
      else stopPolling()
    } catch {
      // ignore
    } finally {
      loadingList.value = false
    }
  }

  async function pollAll() {
    const ids = jobs.value
      .filter((j) => POLLABLE.includes(j.status))
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
    if (!activeJobs.value.length) stopPolling()
  }

  function startPolling() {
    if (!activeJobs.value.length) {
      stopPolling()
      return
    }
    if (pollHandle?.isRunning()) return
    if (pollHandle) {
      pollHandle.restart()
      return
    }
    pollHandle = createVisibilityAwarePoll(() => {
      void pollAll()
    }, POLL_MS)
  }

  function stopPolling() {
    if (pollHandle) {
      pollHandle.stop()
      pollHandle = null
    }
  }

  /** Call after starting an import from any page. */
  function trackJob(job, { notify = true } = {}) {
    if (!job?.id) return
    upsertJob(job)
    if (notify) {
      ElMessage.success(`导入已加入队列（任务 #${job.id}），可到「任务台」查看进度`)
    }
    void pollAll()
    startPolling()
  }

  async function cancelJob(jobId) {
    await cancelFingerprintImportJobApi(jobId)
    await refreshJob(jobId)
    ElMessage.info(`已请求取消导入 #${jobId}`)
  }

  async function restoreFromSession() {
    await syncFromServer()
    const ids = loadPersistedIds()
    await Promise.all(
      ids.map(async (id) => {
        if (jobs.value.some((j) => j.id === id)) return
        try {
          const res = await fetchFingerprintImportJobApi(id)
          const job = normalizeJob(res)
          if (job?.id) upsertJob(job)
        } catch {
          // drop
        }
      }),
    )
    if (activeJobs.value.length) startPolling()
    else stopPolling()
  }

  return {
    jobs,
    loadingList,
    activeJobs,
    visibleJobs,
    hasVisible,
    latestActive,
    trackJob,
    dismissJob,
    clearFinished,
    cancelJob,
    restoreFromSession,
    syncFromServer,
    refreshJob,
    startPolling,
    stopPolling,
  }
})
