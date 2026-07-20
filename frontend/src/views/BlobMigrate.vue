<script setup>
/**
 * BLOB 迁移任务台：管任务（预检 / 全量 / 暂停继续 / 历史）。
 * 扫表建配置、一键迁移 → 数据库模拟；旧库连接 → 模拟页「管理连接」。
 */
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { callWithRetry } from '@/utils/callWithRetry'
import { usePageDataRefresh } from '@/utils/usePageDataRefresh'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  cancelBlobMigrationJobApi,
  clearBlobMigrationJobHistoryApi,
  createBlobMigrationJobApi,
  deleteBlobMigrationJobApi,
  deleteBlobMigrationSourceApi,
  exportBlobMigrationJobErrorsUrl,
  getBlobMigrationJobApi,
  getBlobMigrationSourceApi,
  listBlobMigrationJobsApi,
  listBlobMigrationSourcesApi,
  pauseBlobMigrationJobApi,
  resumeBlobMigrationJobApi,
  retryBlobMigrationJobApi,
  runBlobMigrationApi,
  runGlobalDataSyncApi,
} from '@/api/images'
import ExternalDbConnectionsDialog from '@/components/ExternalDbConnectionsDialog.vue'
import BackgroundExportDock from '@/components/BackgroundExportDock.vue'

const router = useRouter()
const route = useRoute()

const sources = ref([])
const loadingSources = ref(false)
const running = ref(false)
const runResult = ref(null)
const activeJob = ref(null)
const displayJob = ref(null)
const jobHistory = ref([])
const pollTimer = ref(null)
const pollingJobId = ref(null)
const jobRefreshSeq = ref(0)
const globalSyncLoading = ref(false)
const connDialogVisible = ref(false)
const routeApplied = ref(false)

const runOptions = reactive({
  sourceId: null,
  batchSize: 100,
  dryRun: true,
  skipExisting: true,
  warmThumbsAfter: true,
})

const jobInProgress = computed(
  () =>
    activeJob.value &&
    ['pending', 'running'].includes(activeJob.value.status) &&
    !activeJob.value.cancel_requested,
)
const jobCanPause = computed(
  () =>
    activeJob.value &&
    ['pending', 'running'].includes(activeJob.value.status) &&
    !activeJob.value.pause_requested,
)
const jobIsPaused = computed(() => activeJob.value?.status === 'paused')
const clearableJobCount = computed(() => jobHistory.value.length)

function formatSourceColumns(row) {
  const cols = row.blob_columns?.length ? row.blob_columns : [row.blob_column].filter(Boolean)
  return cols.join(', ')
}

async function loadSources() {
  loadingSources.value = true
  try {
    const res = await callWithRetry(() => listBlobMigrationSourcesApi({ includeStats: false }))
    sources.value = res.data || []
    if (!runOptions.sourceId && sources.value.length) {
      runOptions.sourceId = sources.value[0].id
    }
  } catch (err) {
    sources.value = []
    ElMessage.error(err.message || '加载迁移配置失败')
  } finally {
    loadingSources.value = false
  }
}

async function refreshSourceStats(sourceId) {
  if (!sourceId) return
  try {
    const res = await getBlobMigrationSourceApi(sourceId, { includeStats: true })
    const stats = res.data?.stats || null
    const idx = sources.value.findIndex((s) => s.id === sourceId)
    if (idx >= 0) {
      sources.value[idx] = { ...sources.value[idx], ...(res.data || {}), stats }
    }
  } catch {
    // keep row
  }
}

async function removeSource(id) {
  try {
    await ElMessageBox.confirm('确定删除该迁移配置？不影响已迁移图片。', '确认', { type: 'warning' })
    await deleteBlobMigrationSourceApi(id)
    if (runOptions.sourceId === id) runOptions.sourceId = null
    ElMessage.success('已删除')
    await loadSources()
  } catch {
    // cancelled
  }
}

async function loadJobHistoryList() {
  try {
    const res = await listBlobMigrationJobsApi()
    jobHistory.value = res.data || []
  } catch {
    jobHistory.value = []
  }
}

async function loadJobHistory() {
  await loadJobHistoryList()
  const active = jobHistory.value.find((j) => j.status === 'pending' || j.status === 'running')
  if (active && pollingJobId.value !== active.id) {
    setActiveJob(active)
    startJobPolling(active.id)
  }
}

function setActiveJob(job) {
  activeJob.value = job
  if (job) displayJob.value = job
}

function clearActiveJob() {
  activeJob.value = null
  displayJob.value = null
  stopJobPolling()
  running.value = false
}

async function viewJob(row) {
  if (!row?.id) return
  try {
    const res = await getBlobMigrationJobApi(row.id)
    setActiveJob(res.data || row)
  } catch {
    setActiveJob(row)
  }
}

function stopJobPolling() {
  jobRefreshSeq.value += 1
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
  pollingJobId.value = null
}

function formatEta(seconds) {
  if (seconds == null || seconds <= 0) return '—'
  const m = Math.ceil(seconds / 60)
  if (m < 60) return `约 ${m} 分钟`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm ? `约 ${h} 小时 ${rm} 分` : `约 ${h} 小时`
}

function jobStatusLabel(status) {
  const labels = {
    pending: '排队中',
    running: '进行中',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return labels[status] || status
}

function sourceById(sourceId) {
  return sources.value.find((s) => s.id === sourceId) || null
}

function liveStatsForJob(job) {
  if (!job || ['pending', 'running'].includes(job.status)) return null
  return sourceById(job.source_id)?.stats || null
}

function jobNeedsRetry(job) {
  if (!job || ['pending', 'running'].includes(job.status)) return false
  const stats = liveStatsForJob(job)
  if (stats) return Number(stats.pending || 0) > 0
  return Number(job?.failed || 0) > 0
}

function jobHasFailedRows(job) {
  return Number(job?.failed || 0) > 0 || Number(job?.error_count || 0) > 0
}

function jobProgressCount(job) {
  if (!job) return 0
  if (job.display_done != null) return Number(job.display_done)
  return Number(job.succeeded || 0) + Number(job.failed || 0) + Number(job.skipped || 0)
}

function jobProgressTotal(job) {
  if (!job) return 0
  const fromJob = Math.max(Number(job.display_total || 0), Number(job.total_estimate || 0))
  const stats = liveStatsForJob(job)
  const fromStats = stats ? Number(stats.total_with_blob || 0) : 0
  return Math.max(fromJob, fromStats)
}

function formatJobProgress(job) {
  const done = jobProgressCount(job)
  const total = jobProgressTotal(job)
  if (!total) {
    return ['pending', 'running'].includes(job?.status)
      ? `${done} / 扫描中`
      : done > 0
        ? `${done} / ${done}`
        : '0 / 0（无数据）'
  }
  return `${done} / ${total} (${Math.round((100 * done) / total)}%)`
}

function formatLiveProgress(job) {
  if (!job) return '—'
  if (['pending', 'running'].includes(job.status)) {
    const done = jobProgressCount(job)
    const total = jobProgressTotal(job)
    if (!total && String(job.message || '').includes('统计')) {
      return `正在统计待迁移数量…（成功 ${job.succeeded || 0} · 跳过 ${job.skipped || 0} · 失败 ${job.failed || 0}）`
    }
    const totalLabel = total > 0 ? `预估 ${total}` : '扫描中'
    return `已处理 ${done} / ${totalLabel}（成功 ${job.succeeded || 0} · 跳过 ${job.skipped || 0} · 失败 ${job.failed || 0}）`
  }
  const stats = liveStatsForJob(job)
  if (stats) {
    return `已迁移 ${stats.migrated} / 共 ${stats.total_with_blob}（待处理 ${stats.pending}）`
  }
  return formatJobProgress(job)
}

function jobProgressPercent(job) {
  if (!job) return 0
  if (job.percent != null && !['pending', 'running'].includes(job.status)) {
    return Math.min(100, Math.round(Number(job.percent)))
  }
  const done = jobProgressCount(job)
  const total = jobProgressTotal(job)
  if (!total) return 0
  const percent = Math.round((100 * done) / total)
  return ['pending', 'running'].includes(job.status)
    ? Math.min(99, Math.max(0, percent))
    : Math.min(100, Math.max(0, percent))
}

function jobProgressIndeterminate(job) {
  return Boolean(job && ['pending', 'running'].includes(job.status) && !jobProgressTotal(job))
}

async function refreshActiveJob(jobId) {
  const seq = ++jobRefreshSeq.value
  try {
    const res = await getBlobMigrationJobApi(jobId)
    if (seq !== jobRefreshSeq.value || !res?.data) return
    setActiveJob(res.data)
    if (res.data.status === 'paused') {
      stopJobPolling()
      running.value = false
      await loadJobHistoryList()
      return
    }
    if (['completed', 'failed', 'cancelled'].includes(res.data.status)) {
      stopJobPolling()
      running.value = false
      await Promise.all([loadSources(), loadJobHistoryList()])
      if (res.data.source_id) await refreshSourceStats(res.data.source_id)
      if (res.data.status === 'completed') {
        const pending = Number(sourceById(res.data.source_id)?.stats?.pending ?? -1)
        if (pending > 0) ElMessage.warning(`任务结束，仍有 ${pending} 条待迁移`)
        else if (Number(res.data.succeeded || 0) <= 0) {
          ElMessage.warning(res.data.message || '任务结束，但未迁移任何图片')
        } else ElMessage.success(res.message || '迁移已完成')
      } else if (res.data.status === 'cancelled') {
        ElMessage.warning('迁移任务已取消')
      } else if (res.data.status === 'failed') {
        ElMessage.error(res.data.message || '迁移失败')
      }
    }
  } catch {
    // keep last state
  }
}

function startJobPolling(jobId) {
  if (pollingJobId.value === jobId && pollTimer.value) return
  stopJobPolling()
  pollingJobId.value = jobId
  refreshActiveJob(jobId).catch(() => {})
  pollTimer.value = setInterval(() => {
    refreshActiveJob(jobId).catch(() => {})
  }, 3000)
}

async function startFullMigration() {
  if (!runOptions.sourceId) {
    ElMessage.warning('请选择迁移任务')
    return
  }
  if (runOptions.dryRun) {
    ElMessage.info('全量迁移请取消「仅预检」；预检请用「预检一批」')
    return
  }
  running.value = true
  runResult.value = null
  try {
    const res = await createBlobMigrationJobApi({
      sourceId: runOptions.sourceId,
      batchSize: runOptions.batchSize,
      dryRun: false,
      skipExisting: runOptions.skipExisting,
      runAll: true,
      warmThumbsAfter: runOptions.warmThumbsAfter,
    })
    setActiveJob(res.data)
    ElMessage.success(res.message || '全量迁移任务已创建，scheduler 约 10 秒内开始')
    startJobPolling(res.data.id)
    await loadJobHistory()
  } catch (err) {
    running.value = false
    ElMessage.error(err.message || '创建任务失败')
  }
}

async function cancelActiveJob() {
  if (!activeJob.value?.id) return
  try {
    const res = await cancelBlobMigrationJobApi(activeJob.value.id)
    setActiveJob(res.data)
    stopJobPolling()
    running.value = false
    ElMessage.success('迁移任务已取消')
    await loadJobHistory()
  } catch (err) {
    ElMessage.error(err.message || '取消失败')
  }
}

async function pauseActiveJob() {
  if (!activeJob.value?.id) return
  try {
    const res = await pauseBlobMigrationJobApi(activeJob.value.id)
    setActiveJob(res.data)
    if (res.data.status === 'paused') {
      stopJobPolling()
      running.value = false
    }
    ElMessage.success(res.message || '已请求暂停')
    await loadJobHistory()
  } catch (err) {
    ElMessage.error(err.message || '暂停失败')
  }
}

async function resumePausedJob(job) {
  if (!job?.id) return
  try {
    const res = await resumeBlobMigrationJobApi(job.id)
    setActiveJob(res.data)
    running.value = true
    ElMessage.success(res.message || '已继续，正在后台启动')
    startJobPolling(job.id)
    await loadJobHistory()
  } catch (err) {
    ElMessage.error(err.message || '继续失败')
  }
}

async function removeJob(job) {
  if (!job?.id) return
  const force = ['pending', 'running'].includes(job.status)
  try {
    await ElMessageBox.confirm(
      force ? '该任务可能仍在队列中，确定强制删除？' : '确定删除这条任务历史？',
      force ? '强制删除' : '确认',
      { type: 'warning' },
    )
    await deleteBlobMigrationJobApi(job.id)
    if (activeJob.value?.id === job.id) clearActiveJob()
    ElMessage.success('已删除')
    await loadJobHistory()
  } catch {
    // cancelled
  }
}

async function clearJobHistory() {
  if (clearableJobCount.value <= 0) {
    ElMessage.info('没有可清除的历史记录')
    return
  }
  try {
    await ElMessageBox.confirm(
      '确定清除全部任务历史？排队中或进行中的任务也会被强制删除，不影响已迁移的图片。',
      '清除历史',
      { type: 'warning' },
    )
    const res = await clearBlobMigrationJobHistoryApi()
    if (activeJob.value) clearActiveJob()
    ElMessage.success(res.message || '已清除全部历史')
    await loadJobHistory()
  } catch {
    // cancelled
  }
}

async function retryFailedJob(job) {
  if (!job?.id) return
  if (!jobHasFailedRows(job)) {
    runOptions.sourceId = job.source_id
    await startFullMigration()
    return
  }
  try {
    const res = await retryBlobMigrationJobApi({
      parentJobId: job.id,
      batchSize: runOptions.batchSize,
      warmThumbsAfter: runOptions.warmThumbsAfter,
    })
    setActiveJob(res.data)
    running.value = true
    ElMessage.success('重试任务已创建')
    startJobPolling(res.data.id)
    await loadJobHistory()
  } catch (err) {
    ElMessage.error(err.message || '创建重试任务失败')
  }
}

function downloadJobErrors(job) {
  if (!job?.id) return
  const auth = useAuthStore()
  const url = exportBlobMigrationJobErrorsUrl(job.id)
  fetch(url, { headers: { Authorization: `Bearer ${auth.accessToken}` } })
    .then((res) => {
      if (!res.ok) throw new Error('导出失败')
      return res.blob()
    })
    .then((blob) => {
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `blob_migration_job_${job.id}_errors.csv`
      link.click()
      URL.revokeObjectURL(link.href)
    })
    .catch((err) => ElMessage.error(err.message || '导出失败'))
}

async function runGlobalDataSync() {
  globalSyncLoading.value = true
  try {
    const res = await runGlobalDataSyncApi({ batch_size: 200 })
    ElMessage.success(res.message || '全局数据同步完成')
  } catch (err) {
    ElMessage.error(err.message || '全局数据同步失败')
  } finally {
    globalSyncLoading.value = false
  }
}

async function executeMigration() {
  if (!runOptions.sourceId) {
    ElMessage.warning('请选择迁移任务')
    return
  }
  running.value = true
  runResult.value = null
  try {
    const res = await runBlobMigrationApi({
      sourceId: runOptions.sourceId,
      batchSize: runOptions.batchSize,
      dryRun: runOptions.dryRun,
      skipExisting: runOptions.skipExisting,
    })
    runResult.value = res.data
    ElMessage.success(res.message || '执行完成')
    await loadSources()
  } catch (err) {
    if (err.data) runResult.value = err.data
    ElMessage.error(err.message || '执行失败')
  } finally {
    running.value = false
  }
}

async function applyRouteQuery() {
  const q = route.query || {}
  const sourceId = Number(q.sourceId)
  if (sourceId && !Number.isNaN(sourceId)) {
    runOptions.sourceId = sourceId
  }
  const jobId = Number(q.jobId)
  if (jobId && !Number.isNaN(jobId)) {
    try {
      const res = await getBlobMigrationJobApi(jobId)
      if (res.data) {
        setActiveJob(res.data)
        if (res.data.source_id) runOptions.sourceId = res.data.source_id
        if (['pending', 'running'].includes(res.data.status)) {
          startJobPolling(res.data.id)
        }
      }
    } catch {
      // ignore bad jobId
    }
  }
}

async function refreshConsole() {
  await Promise.all([loadSources(), loadJobHistory()])
  if (!routeApplied.value) {
    await applyRouteQuery()
    routeApplied.value = true
  }
}

usePageDataRefresh(refreshConsole, {
  isEmpty: () => !sources.value.length && !jobHistory.value.length,
  intervalMs: 2500,
  maxEmptyRetries: 6,
})

watch(
  () => [route.query.sourceId, route.query.jobId],
  () => {
    routeApplied.value = false
    void applyRouteQuery().then(() => {
      routeApplied.value = true
    })
  },
)

onUnmounted(() => {
  stopJobPolling()
})
</script>

<template>
  <div class="migrate-page">
    <div class="page-card">
      <div class="page-head">
        <div>
          <h2 class="page-title">迁移任务台</h2>
          <p class="page-desc">
            管理迁移源与后台任务（预检、全量、暂停/继续），以及「数据库模拟」发起的路径导出进度。
            日常扫表建配置、一键迁移请用「数据库模拟」。
          </p>
        </div>
        <div class="page-actions">
          <el-button @click="connDialogVisible = true">管理旧库连接</el-button>
          <el-button type="primary" plain @click="router.push('/blob-browse')">打开数据库模拟</el-button>
        </div>
      </div>

      <el-alert
        title="部署更新 backend/scheduler 前请先暂停进行中的任务。配置与启迁在「数据库模拟」完成。"
        type="info"
        show-icon
        :closable="false"
        class="info-alert"
      />

      <section class="section">
        <BackgroundExportDock />
      </section>

      <section class="section">
        <div class="section-head-row">
          <h3>1. 已保存的迁移源</h3>
          <div>
            <el-button :loading="loadingSources" @click="loadSources">刷新</el-button>
            <el-button type="primary" plain :loading="globalSyncLoading" @click="runGlobalDataSync">
              全局数据同步
            </el-button>
          </div>
        </div>
        <p class="field-hint">
          源由「数据库模拟」创建配置 / 一键迁移时自动生成。此处可选用、看进度或删除。
        </p>
        <el-table v-loading="loadingSources" :data="sources" size="small" border empty-text="暂无迁移源，请先到数据库模拟创建配置并一键迁移">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column label="源" min-width="220">
            <template #default="{ row }">
              {{ row.db_alias }} · {{ row.source_table }}
              <span v-if="row.source_object_type === 'view'"> [视图→{{ row.path_lookup_table || '?' }}]</span>
              · {{ formatSourceColumns(row) }}
            </template>
          </el-table-column>
          <el-table-column label="进度" min-width="200">
            <template #default="{ row }">
              <span v-if="row.stats">
                已迁移 {{ row.stats.migrated }} / 共 {{ row.stats.total_with_blob }}
                <el-tag v-if="row.stats.pending > 0" size="small" type="warning" style="margin-left: 8px">
                  待处理 {{ row.stats.pending }}
                </el-tag>
                <el-tag v-else size="small" type="success" style="margin-left: 8px">已完成</el-tag>
              </span>
              <el-button v-else link type="primary" size="small" @click="refreshSourceStats(row.id)">
                加载进度
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="runOptions.sourceId = row.id">选用</el-button>
              <el-button link type="danger" @click="removeSource(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="section">
        <h3>2. 执行与监控</h3>
        <el-form inline class="run-form">
          <el-form-item label="任务">
            <el-select v-model="runOptions.sourceId" placeholder="选择迁移源" style="min-width: 220px">
              <el-option
                v-for="src in sources"
                :key="src.id"
                :label="`${src.id}: ${src.name || src.source_table}`"
                :value="src.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="批次大小">
            <el-input-number v-model="runOptions.batchSize" :min="1" :max="500" />
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="runOptions.dryRun">仅预检（不写盘）</el-checkbox>
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="runOptions.skipExisting">跳过已迁移</el-checkbox>
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="runOptions.warmThumbsAfter">完成后预热缩略图</el-checkbox>
          </el-form-item>
          <el-form-item>
            <el-button :loading="running && !jobInProgress" @click="executeMigration">预检一批</el-button>
            <el-button
              type="primary"
              :loading="jobInProgress"
              :disabled="runOptions.dryRun || jobInProgress"
              @click="startFullMigration"
            >
              <el-icon><Refresh /></el-icon>
              开始全量迁移
            </el-button>
            <el-button v-if="jobCanPause" type="warning" plain @click="pauseActiveJob">暂停</el-button>
            <el-button v-if="jobInProgress" type="danger" plain @click="cancelActiveJob">取消</el-button>
            <el-button v-if="jobIsPaused" type="primary" @click="resumePausedJob(displayJob)">继续迁移</el-button>
          </el-form-item>
        </el-form>

        <div v-if="displayJob" class="job-progress-panel">
          <div class="job-progress-head">
            <span>{{ jobStatusLabel(displayJob.status) }}</span>
            <span v-if="displayJob.eta_seconds != null" class="job-eta">
              剩余 {{ formatEta(displayJob.eta_seconds) }}
            </span>
          </div>
          <el-progress
            :percentage="jobProgressPercent(displayJob)"
            :indeterminate="jobProgressIndeterminate(displayJob)"
            :status="
              !jobInProgress && Number(liveStatsForJob(displayJob)?.pending ?? 1) <= 0
                ? 'success'
                : displayJob.status === 'failed' && jobNeedsRetry(displayJob)
                  ? 'exception'
                  : displayJob.status === 'completed'
                    ? 'success'
                    : undefined
            "
            :stroke-width="16"
            striped
            :striped-flow="jobInProgress && displayJob.status === 'running'"
          />
          <p class="job-stats">{{ formatLiveProgress(displayJob) }}</p>
          <p v-if="jobInProgress" class="job-message field-hint">
            任务由 scheduler 执行；更新部署前请先点「暂停」。
          </p>
          <p v-else-if="jobIsPaused" class="job-message field-hint">
            任务已暂停，可安全更新 backend/scheduler，完成后点「继续迁移」。
          </p>
          <p v-else-if="displayJob.message" class="job-message">{{ displayJob.message }}</p>
          <div v-if="displayJob.recent_errors?.length && jobHasFailedRows(displayJob)" class="job-errors">
            <div v-for="(err, idx) in displayJob.recent_errors" :key="idx" class="job-error-line">
              {{ err.source_pk }}: {{ err.error }}
            </div>
          </div>
          <div v-if="(jobNeedsRetry(displayJob) || jobIsPaused) && !jobInProgress" class="job-actions">
            <el-button v-if="jobIsPaused" size="small" type="primary" @click="resumePausedJob(displayJob)">
              继续迁移
            </el-button>
            <el-button v-else size="small" type="primary" @click="retryFailedJob(displayJob)">
              {{ jobHasFailedRows(displayJob) ? '重试失败项' : '继续迁移待处理项' }}
            </el-button>
            <el-button
              v-if="jobHasFailedRows(displayJob)"
              size="small"
              @click="downloadJobErrors(displayJob)"
            >
              导出错误 CSV
            </el-button>
          </div>
        </div>

        <el-table
          v-if="runResult?.items?.length"
          :data="runResult.items"
          size="small"
          border
          class="result-table"
          max-height="240"
        >
          <el-table-column prop="source_id" label="源 ID" width="100" />
          <el-table-column prop="source_column" label="BLOB 列" width="100" />
          <el-table-column prop="filename" label="文件名" min-width="160" />
          <el-table-column label="结果" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.skipped" type="info">跳过</el-tag>
              <el-tag v-else-if="row.success" type="success">成功</el-tag>
              <el-tag v-else type="danger">失败</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="image_info_id" label="image_info" width="100" />
          <el-table-column prop="error" label="说明" min-width="160" show-overflow-tooltip />
        </el-table>

        <div v-if="jobHistory.length" class="job-history-head">
          <h4 class="subsection-title">任务记录</h4>
          <el-button
            size="small"
            type="danger"
            plain
            :disabled="clearableJobCount <= 0"
            @click="clearJobHistory"
          >
            清除记录
          </el-button>
        </div>
        <el-table v-if="jobHistory.length" :data="jobHistory" size="small" border max-height="280">
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">{{ jobStatusLabel(row.status) }}</template>
          </el-table-column>
          <el-table-column label="当前进度" min-width="220">
            <template #default="{ row }">{{ formatLiveProgress(row) }}</template>
          </el-table-column>
          <el-table-column prop="create_time" label="创建时间" min-width="160" />
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <el-button link type="primary" @click="viewJob(row)">查看</el-button>
              <el-button v-if="row.status === 'paused'" link type="primary" @click="resumePausedJob(row)">
                继续
              </el-button>
              <el-button v-else-if="jobNeedsRetry(row)" link type="primary" @click="retryFailedJob(row)">
                {{ jobHasFailedRows(row) ? '重试失败' : '继续迁移' }}
              </el-button>
              <el-button link type="danger" @click="removeJob(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <ExternalDbConnectionsDialog v-model="connDialogVisible" />
  </div>
</template>

<style scoped>
.migrate-page { max-width: 1100px; }
.page-card {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 20px 24px 28px;
  box-shadow: 0 1px 4px rgb(0 0 0 / 6%);
}
.page-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  flex-wrap: wrap;
}
.page-title { margin: 0 0 6px; font-size: 22px; }
.page-desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
  max-width: 720px;
}
.page-actions { display: flex; gap: 8px; flex-shrink: 0; }
.info-alert { margin: 14px 0 8px; }
.section {
  margin-top: 22px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.section h3 { margin: 0 0 10px; font-size: 16px; }
.section-head-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.section-head-row h3 { margin: 0; }
.field-hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.run-form { margin-bottom: 8px; }
.job-progress-panel {
  margin: 12px 0;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}
.job-progress-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
}
.job-eta { font-weight: 400; color: var(--el-text-color-secondary); }
.job-stats { margin: 8px 0 0; font-size: 13px; }
.job-message { margin: 6px 0 0; font-size: 12px; }
.job-errors {
  margin-top: 8px;
  max-height: 120px;
  overflow: auto;
  font-size: 12px;
  color: var(--el-color-danger);
}
.job-error-line { padding: 2px 0; }
.job-actions { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
.result-table { margin-top: 12px; }
.job-history-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 18px 0 8px;
}
.subsection-title { margin: 0; font-size: 14px; }
</style>
