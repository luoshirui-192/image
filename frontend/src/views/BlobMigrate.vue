<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { callWithRetry } from '@/utils/callWithRetry'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Refresh, Search } from '@element-plus/icons-vue'
import {
  createBlobMigrationSourceApi,
  createBlobTableViewApi,
  createExternalDbConnectionApi,
  createBlobMigrationJobApi,
  cancelBlobMigrationJobApi,
  pauseBlobMigrationJobApi,
  resumeBlobMigrationJobApi,
  clearBlobMigrationJobHistoryApi,
  deleteBlobMigrationJobApi,
  deleteBlobMigrationSourceApi,
  deleteExternalDbConnectionApi,
  discoverBlobTablesApi,
  exportBlobMigrationJobErrorsUrl,
  getBlobMigrationJobApi,
  listBlobMigrationDatabasesApi,
  listBlobMigrationJobsApi,
  listBlobMigrationSourcesApi,
  getBlobMigrationSourceApi,
  listExternalDbConnectionsApi,
  provisionExternalDbTableViewsApi,
  retryBlobMigrationJobApi,
  runBlobMigrationApi,
  runGlobalDataSyncApi,
  testExternalDbConnectionApi,
  testSavedExternalDbConnectionApi,
} from '@/api/images'

const router = useRouter()
const route = useRoute()

const databases = ref([])
const connections = ref([])
const discoveredTables = ref([])
const sources = ref([])
const discovering = ref(false)
const saving = ref(false)
const savingView = ref(false)
const running = ref(false)
const runResult = ref(null)
const activeJob = ref(null)
const displayJob = ref(null)
const jobHistory = ref([])
const pollTimer = ref(null)
const pollingJobId = ref(null)
const jobRefreshSeq = ref(0)

const globalSyncLoading = ref(false)

const form = reactive({
  name: '',
  dbAlias: 'default',
  sourceTable: '',
  sourcePkColumn: 'id',
  blobColumn: '',
  blobColumns: [],
  sourceObjectType: 'table',
  pathLookupTable: '',
  nameColumn: '',
  suffixColumn: '',
  tags: '',
  whereClause: '',
})

const runOptions = reactive({
  sourceId: null,
  batchSize: 100,
  dryRun: true,
  skipExisting: true,
  warmThumbsAfter: true,
})

const connForm = reactive({
  name: '',
  host: '',
  port: 3306,
  db_name: '',
  username: '',
  password: '',
  charset: 'utf8',
  remark: '',
})
const connSaving = ref(false)
const connTesting = ref(false)
const provisionConnId = ref(null)

const selectedDb = computed(() => databases.value.find((d) => d.alias === form.dbAlias))

const discoveredColumnsForTable = computed(() => {
  const row = discoveredTables.value.find((item) => item.table === form.sourceTable)
  return row?.columns || []
})

function dbOptionLabel(db) {
  if (db.label) {
    return `${db.label} (${db.name}@${db.host || 'local'})`
  }
  return `${db.alias} (${db.name}@${db.host || 'local'})`
}

async function loadConnections() {
  try {
    const res = await callWithRetry(() => listExternalDbConnectionsApi())
    connections.value = res.data || []
  } catch {
    connections.value = []
  }
}

async function loadDatabases() {
  try {
    const res = await callWithRetry(() => listBlobMigrationDatabasesApi())
    databases.value = res.data || []
    if (!databases.value.some((d) => d.alias === form.dbAlias) && databases.value.length) {
      form.dbAlias = databases.value[0].alias
    }
  } catch {
    databases.value = [{ alias: 'default', label: '本系统库', name: 'default', host: '' }]
  }
}

async function saveConnection() {
  if (!connForm.name.trim() || !connForm.host.trim() || !connForm.db_name.trim() || !connForm.username.trim()) {
    ElMessage.warning('请填写连接名称、主机、库名和用户名')
    return
  }
  if (!connForm.password) {
    ElMessage.warning('请填写密码')
    return
  }
  connSaving.value = true
  try {
    const res = await createExternalDbConnectionApi({
      name: connForm.name.trim(),
      host: connForm.host.trim(),
      port: Number(connForm.port) || 3306,
      db_name: connForm.db_name.trim(),
      username: connForm.username.trim(),
      password: connForm.password,
      charset: connForm.charset || 'utf8',
      remark: connForm.remark.trim(),
    })
    ElMessage.success(res.message || '旧库连接已保存')
    connForm.password = ''
    await Promise.all([loadConnections(), loadDatabases()])
  } catch (err) {
    ElMessage.error(err.message || '保存失败')
  } finally {
    connSaving.value = false
  }
}

async function testNewConnection() {
  if (!connForm.host.trim() || !connForm.db_name.trim() || !connForm.username.trim() || !connForm.password) {
    ElMessage.warning('测试连接需填写主机、库名、用户名和密码')
    return
  }
  connTesting.value = true
  try {
    const res = await testExternalDbConnectionApi({
      name: connForm.name.trim() || 'test',
      host: connForm.host.trim(),
      port: Number(connForm.port) || 3306,
      db_name: connForm.db_name.trim(),
      username: connForm.username.trim(),
      password: connForm.password,
      charset: connForm.charset || 'utf8',
    })
    ElMessage.success(res.message || '连接成功')
  } catch (err) {
    ElMessage.error(err.message || '连接失败')
  } finally {
    connTesting.value = false
  }
}

async function testSavedConnection(row) {
  connTesting.value = true
  try {
    const res = await testSavedExternalDbConnectionApi(row.id)
    ElMessage.success(res.message || '连接成功')
    await loadConnections()
  } catch (err) {
    ElMessage.error(err.message || '连接失败')
    await loadConnections()
  } finally {
    connTesting.value = false
  }
}

async function syncConnectionTableViews(row) {
  provisionConnId.value = row.id
  try {
    const res = await provisionExternalDbTableViewsApi(row.id)
    ElMessage.success(res.message || '表视图同步完成')
  } catch (err) {
    ElMessage.error(err.message || '表视图同步失败')
  } finally {
    provisionConnId.value = null
  }
}

async function removeConnection(row) {
  try {
    await ElMessageBox.confirm(`确定删除连接「${row.name}」？`, '确认', { type: 'warning' })
    await deleteExternalDbConnectionApi(row.id)
    ElMessage.success('已删除')
    await Promise.all([loadConnections(), loadDatabases()])
  } catch {
    // cancelled or error handled globally
  }
}

function useConnection(row) {
  form.dbAlias = row.alias
}

async function loadSources() {
  try {
    const res = await callWithRetry(() => listBlobMigrationSourcesApi({ includeStats: false }))
    sources.value = res.data || []
    if (!runOptions.sourceId && sources.value.length) {
      runOptions.sourceId = sources.value[0].id
    }
  } catch (err) {
    sources.value = []
    ElMessage.error(err.message || '加载迁移配置失败')
  }
}

async function refreshSourceStats(sourceId) {
  if (!sourceId) return
  try {
    const res = await getBlobMigrationSourceApi(sourceId, { includeStats: true })
    const stats = res.data?.stats || null
    const idx = sources.value.findIndex((s) => s.id === sourceId)
    if (idx >= 0) {
      sources.value[idx] = {
        ...sources.value[idx],
        ...(res.data || {}),
        stats,
      }
    }
  } catch {
    // Keep the source row visible even if stats timing out.
  }
}

async function discoverTables() {
  discovering.value = true
  discoveredTables.value = []
  try {
    const res = await discoverBlobTablesApi({ dbAlias: form.dbAlias })
    discoveredTables.value = res.data?.tables || []
    if (!discoveredTables.value.length) {
      ElMessage.info('未发现含 BLOB 的表')
    }
  } catch (err) {
    ElMessage.error(err.message || '扫描失败')
  } finally {
    discovering.value = false
  }
}

function applyDiscovery(row, col) {
  form.sourceTable = row.table
  form.sourceObjectType = row.object_type || 'table'
  if (col) {
    const columnName = col.column
    if (!form.blobColumns.includes(columnName)) {
      form.blobColumns.push(columnName)
    }
    form.blobColumn = form.blobColumns[0] || columnName
  } else if (row.columns?.length) {
    form.blobColumns = row.columns.map((item) => item.column)
    form.blobColumn = form.blobColumns[0] || ''
  }
}

function applyAllDiscoveryColumns(row) {
  applyDiscovery(row, null)
}

function formatSourceColumns(row) {
  const cols = row.blob_columns?.length ? row.blob_columns : [row.blob_column].filter(Boolean)
  return cols.join(', ')
}

function migrationPayloadBase() {
  const dbName = selectedDb.value?.name
  return {
    name: form.name.trim() || undefined,
    db_alias: form.dbAlias,
    database_name: dbName && dbName !== 'default' ? dbName : undefined,
    source_table: form.sourceTable.trim(),
    source_pk_column: form.sourcePkColumn.trim() || 'id',
    blob_column: (form.blobColumns[0] || form.blobColumn || '').trim(),
    blob_columns: form.blobColumns.length ? [...form.blobColumns] : undefined,
    source_object_type: form.sourceObjectType || 'table',
    path_lookup_table: form.pathLookupTable.trim() || undefined,
    where_clause: form.whereClause.trim(),
  }
}

async function saveView() {
  if (!form.sourceTable || (!form.blobColumn && !form.blobColumns.length)) {
    ElMessage.warning('请填写源表与 BLOB 列')
    return
  }

  savingView.value = true
  try {
    const res = await createBlobTableViewApi({
      ...migrationPayloadBase(),
      name: form.name.trim() || form.sourceTable.trim(),
    })
    ElMessage.success('配置已保存')
    const viewId = res.data?.id
    if (viewId) {
      router.push({ path: '/blob-browse', query: { viewId: String(viewId) } })
    }
  } catch (err) {
    ElMessage.error(err.message || '保存配置失败')
  } finally {
    savingView.value = false
  }
}

async function saveSource() {
  if (!form.sourceTable || (!form.blobColumn && !form.blobColumns.length)) {
    ElMessage.warning('请填写源表与 BLOB 列')
    return
  }
  saving.value = true
  try {
    await createBlobMigrationSourceApi({
      ...migrationPayloadBase(),
      name: form.name.trim() || `${form.sourceTable}.${form.blobColumns[0] || form.blobColumn}`,
      name_column: form.nameColumn.trim(),
      suffix_column: form.suffixColumn.trim(),
      tags: form.tags.trim(),
    })
    ElMessage.success('迁移配置已保存')
    await loadSources()
  } catch (err) {
    ElMessage.error(err.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function removeSource(id) {
  try {
    await ElMessageBox.confirm('删除配置不会撤销已迁移的数据，确定删除？', '确认', { type: 'warning' })
    await deleteBlobMigrationSourceApi(id)
    ElMessage.success('已删除')
    if (runOptions.sourceId === id) {
      runOptions.sourceId = null
    }
    await loadSources()
  } catch {
    // cancelled
  }
}

async function loadJobHistoryList() {
  try {
    const res = await callWithRetry(() => listBlobMigrationJobsApi())
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
  if (job) {
    displayJob.value = job
  }
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
  if (job.display_total != null && Number(job.display_total) > 0) {
    return Number(job.display_total)
  }
  const stats = liveStatsForJob(job)
  if (stats) return Number(stats.total_with_blob || 0)
  return Number(job.total_estimate || 0)
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
  const percent = Math.round((100 * done) / total)
  return `${done} / ${total} (${percent}%)`
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
  return Boolean(
    job &&
      ['pending', 'running'].includes(job.status) &&
      !jobProgressTotal(job),
  )
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
      // One opt-in COUNT after finish — not a fan-out on page load.
      if (res.data.source_id) {
        await refreshSourceStats(res.data.source_id)
      }
      if (res.data.status === 'completed') {
        const pending = Number(sourceById(res.data.source_id)?.stats?.pending ?? -1)
        if (pending > 0) {
          ElMessage.warning(`任务结束，仍有 ${pending} 条待迁移`)
        } else if (Number(res.data.succeeded || 0) <= 0) {
          ElMessage.warning(res.data.message || '任务结束，但未迁移任何图片')
        } else {
          ElMessage.success(res.message || '迁移已完成')
        }
      } else if (res.data.status === 'cancelled') {
        ElMessage.warning('迁移任务已取消')
      } else if (res.data.status === 'failed') {
        ElMessage.error(res.data.message || '迁移失败')
      }
    }
  } catch {
    // keep last known job state on transient poll errors
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
    ElMessage.success(res.message || '已排队，scheduler 将继续执行')
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
      force
        ? '该任务可能仍在队列中，确定强制删除这条记录？'
        : '确定删除这条任务历史？',
      force ? '强制删除' : '确认',
      { type: 'warning' },
    )
    await deleteBlobMigrationJobApi(job.id)
    if (activeJob.value?.id === job.id) {
      clearActiveJob()
    }
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
    if (activeJob.value) {
      clearActiveJob()
    }
    ElMessage.success(res.message || '已清除全部历史')
    await loadJobHistory()
  } catch {
    // cancelled
  }
}

async function retryFailedJob(job) {
  if (!job?.id) return
  // If there are failed rows, retry those; otherwise start another full pass for remaining pending.
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
    if (err.data) {
      runResult.value = err.data
    }
    ElMessage.error(err.message || '执行失败')
  } finally {
    running.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadConnections(), loadDatabases(), loadSources(), loadJobHistory()])
  applyRoutePrefill()
})

function applyRoutePrefill() {
  const q = route.query || {}
  if (q.dbAlias) form.dbAlias = String(q.dbAlias)
  if (q.sourceTable) form.sourceTable = String(q.sourceTable)
  if (q.objectType === 'view' || q.objectType === 'table') {
    form.sourceObjectType = String(q.objectType)
  }
  if (q.blobColumns) {
    const cols = String(q.blobColumns)
      .split(',')
      .map((c) => c.trim())
      .filter(Boolean)
    if (cols.length) {
      form.blobColumns = cols
      form.blobColumn = cols[0]
    }
  }
  if (q.sourcePkColumn) form.sourcePkColumn = String(q.sourcePkColumn)
}

onUnmounted(() => {
  stopJobPolling()
})
</script>

<template>
  <div class="migrate-page">
    <div class="page-card">
      <h2 class="page-title">数据库 BLOB 迁移</h2>
      <p class="page-desc">
        可在下方<strong>直接添加旧库连接</strong>（无需改 .env），然后从旧表 BLOB 列导出到
        <code>upload/</code> 并写入 <code>image_info</code>；原表结构<strong>不会修改</strong>。
      </p>

      <el-alert
        title="管理员专用。先添加并测试旧库连接，再扫描 BLOB 表。建议先预检，再正式迁移。"
        type="warning"
        show-icon
        :closable="false"
        class="info-alert"
      />

      <section class="section">
        <h3>1. 连接旧库</h3>
        <el-form label-width="110px" class="compact-form">
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item label="连接名称" required>
                <el-input v-model="connForm.name" placeholder="例如：生产旧库" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="主机" required>
                <el-input
                  v-model="connForm.host"
                  placeholder="192.168.1.154 或 host.docker.internal"
                  clearable
                />
                <div class="field-hint">Docker 部署时，本机 MySQL 请填 <code>host.docker.internal</code> 或局域网 IP，不要用 127.0.0.1</div>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="端口">
                <el-input-number v-model="connForm.port" :min="1" :max="65535" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="数据库" required>
                <el-input v-model="connForm.db_name" placeholder="legacy_db" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="用户名" required>
                <el-input v-model="connForm.username" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="密码" required>
                <el-input v-model="connForm.password" type="password" show-password />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="备注">
                <el-input v-model="connForm.remark" maxlength="500" clearable />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item>
            <el-button type="primary" plain :loading="connTesting" @click="testNewConnection">
              测试连接
            </el-button>
            <el-button type="primary" :loading="connSaving" @click="saveConnection">
              保存连接
            </el-button>
          </el-form-item>
        </el-form>

        <el-table :data="connections" size="small" border empty-text="尚未配置旧库连接">
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column label="地址" min-width="180">
            <template #default="{ row }">{{ row.username }}@{{ row.host }}:{{ row.port }}/{{ row.db_name }}</template>
          </el-table-column>
          <el-table-column label="最近测试" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.last_test_ok === 1" type="success" size="small">成功</el-tag>
              <el-tag v-else-if="row.last_test_at" type="danger" size="small">失败</el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="260">
            <template #default="{ row }">
              <el-button link type="primary" @click="useConnection(row)">选用</el-button>
              <el-button link type="primary" :loading="connTesting" @click="testSavedConnection(row)">测试</el-button>
              <el-button
                link
                type="primary"
                :loading="provisionConnId === row.id"
                @click="syncConnectionTableViews(row)"
              >
                同步表视图
              </el-button>
              <el-button link type="danger" @click="removeConnection(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="section">
        <h3>2. 选择数据源并扫描</h3>
        <el-form label-width="110px" class="compact-form">
          <el-form-item label="数据库">
            <el-select v-model="form.dbAlias" style="min-width: 320px">
              <el-option
                v-for="db in databases"
                :key="db.alias"
                :label="dbOptionLabel(db)"
                :value="db.alias"
              />
            </el-select>
            <el-button
              type="primary"
              plain
              :loading="discovering"
              class="ml-8"
              @click="discoverTables"
            >
              <el-icon><Search /></el-icon>
              扫描 BLOB 表
            </el-button>
          </el-form-item>
          <div v-if="selectedDb" class="field-hint">
            当前：<code>{{ selectedDb.alias }}</code>
            <span v-if="selectedDb.type === 'external'">（Web 配置的旧库）</span>
            <span v-else-if="selectedDb.type === 'system'">（本系统库，旧表若在同一库可选此项）</span>
          </div>
        </el-form>

        <el-table
          v-if="discoveredTables.length"
          :data="discoveredTables"
          size="small"
          border
          class="discover-table"
        >
          <el-table-column prop="table" label="表/视图" width="200" />
          <el-table-column label="BLOB 列">
            <template #default="{ row }">
              <el-tag
                v-for="col in row.columns"
                :key="col.column"
                class="col-tag"
                :type="form.blobColumns.includes(col.column) ? 'success' : 'info'"
                @click="applyDiscovery(row, col)"
              >
                {{ col.column }} ({{ col.data_type }})
              </el-tag>
              <el-button
                v-if="row.columns?.length > 1"
                link
                type="primary"
                size="small"
                class="ml-4"
                @click="applyAllDiscoveryColumns(row)"
              >
                全选列
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="discoveredTables.length" class="field-hint">点击列名可填入下方表单</p>
      </section>

      <section class="section">
        <h3>3. 配置迁移任务</h3>
        <el-form label-width="110px" class="compact-form">
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item label="任务名称">
                <el-input v-model="form.name" placeholder="可选" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="源表" required>
                <el-input v-model="form.sourceTable" placeholder="legacy_images" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="主键列">
                <el-input v-model="form.sourcePkColumn" placeholder="id" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="对象类型">
                <el-select v-model="form.sourceObjectType" style="width: 100%">
                  <el-option label="表" value="table" />
                  <el-option label="数据库视图" value="view" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="BLOB 列" required>
                <el-select
                  v-model="form.blobColumns"
                  multiple
                  collapse-tags
                  collapse-tags-tooltip
                  placeholder="选择一个或多个 BLOB 列"
                  style="width: 100%"
                  @change="form.blobColumn = form.blobColumns[0] || ''"
                >
                  <el-option
                    v-for="col in discoveredColumnsForTable"
                    :key="col.column"
                    :label="`${col.column} (${col.data_type})`"
                    :value="col.column"
                  />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col v-if="form.sourceObjectType === 'view'" :xs="24" :sm="8">
              <el-form-item label="路径映射表">
                <el-input
                  v-model="form.pathLookupTable"
                  placeholder="留空则自动识别简单视图"
                  clearable
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="文件名列">
                <el-input v-model="form.nameColumn" placeholder="可选" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="后缀列">
                <el-input v-model="form.suffixColumn" placeholder="可选" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="24">
              <el-form-item label="WHERE 条件">
                <el-input
                  v-model="form.whereClause"
                  placeholder="例如：status = 1（不含 WHERE 关键字）"
                  clearable
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="24">
              <el-form-item label="标签">
                <el-input v-model="form.tags" placeholder="写入 image_info.tags" maxlength="500" clearable />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item>
            <el-button type="primary" :loading="saving" @click="saveSource">
              <el-icon><Connection /></el-icon>
              保存迁移配置
            </el-button>
            <el-button type="success" plain :loading="savingView" @click="saveView">
              保存为表配置
            </el-button>
            <span class="field-hint inline-hint">用于远程表/对象的数据查看，BLOB 列显示为本地路径，不执行迁移</span>
          </el-form-item>
        </el-form>
      </section>

      <section class="section">
        <div class="section-head-row">
          <h3>4. 已保存的任务</h3>
          <el-button type="primary" plain :loading="globalSyncLoading" @click="runGlobalDataSync">
            全局数据同步
          </el-button>
        </div>
        <p class="field-hint">
          所有迁移配置默认开启后台自动同步（Scheduler 定时检测外部 BLOB 变更并重迁）。可手动触发一次全量数据同步。
        </p>
        <el-table :data="sources" size="small" border empty-text="暂无配置">
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
                <el-tag
                  v-if="row.stats.pending > 0"
                  size="small"
                  type="warning"
                  style="margin-left: 8px"
                >待处理 {{ row.stats.pending }}</el-tag>
                <el-tag v-else size="small" type="success" style="margin-left: 8px">已完成</el-tag>
              </span>
              <el-button
                v-else
                link
                type="primary"
                size="small"
                @click="refreshSourceStats(row.id)"
              >
                加载进度
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button link type="primary" @click="runOptions.sourceId = row.id">选用</el-button>
              <el-button link type="danger" @click="removeSource(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="section">
        <h3>5. 执行迁移</h3>
        <el-form inline class="run-form">
          <el-form-item label="任务">
            <el-select v-model="runOptions.sourceId" placeholder="选择任务" style="min-width: 220px">
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
            <el-checkbox v-model="runOptions.warmThumbsAfter">完成后预热缩略图（默认开启）</el-checkbox>
          </el-form-item>
          <el-form-item>
            <el-button :loading="running && !jobInProgress" @click="executeMigration">
              预检一批
            </el-button>
            <el-button type="primary" :loading="jobInProgress" :disabled="runOptions.dryRun || jobInProgress" @click="startFullMigration">
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
            <span v-if="displayJob.eta_seconds != null" class="job-eta">剩余 {{ formatEta(displayJob.eta_seconds) }}</span>
          </div>
          <el-progress
            :percentage="jobProgressPercent(displayJob)"
            :indeterminate="jobProgressIndeterminate(displayJob)"
            :status="!jobInProgress && Number(liveStatsForJob(displayJob)?.pending ?? 1) <= 0
              ? 'success'
              : displayJob.status === 'failed' && jobNeedsRetry(displayJob)
                ? 'exception'
                : displayJob.status === 'completed'
                  ? 'success'
                  : undefined"
            :stroke-width="16"
            striped
            :striped-flow="jobInProgress && displayJob.status === 'running'"
          />
          <p class="job-stats">
            {{ formatLiveProgress(displayJob) }}
          </p>
          <p v-if="jobInProgress" class="job-message field-hint">
            任务由 scheduler 执行；更新部署前请先点「暂停」。首批可能较慢（预取 BLOB 期间进度暂不动）。
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
            <el-button v-if="jobHasFailedRows(displayJob)" size="small" @click="downloadJobErrors(displayJob)">导出错误 CSV</el-button>
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
              <el-button v-if="row.status === 'paused'" link type="primary" @click="resumePausedJob(row)">继续</el-button>
              <el-button v-else-if="jobNeedsRetry(row)" link type="primary" @click="retryFailedJob(row)">
                {{ jobHasFailedRows(row) ? '重试失败' : '继续迁移' }}
              </el-button>
              <el-button link type="danger" @click="removeJob(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>
  </div>
</template>

<style scoped>
.migrate-page {
  max-width: 1100px;
}

.page-card {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 24px;
  box-shadow: 0 1px 4px rgb(0 0 0 / 6%);
}

.page-title {
  margin: 0 0 8px;
  font-size: 20px;
}

.page-desc {
  margin: 0 0 16px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.info-alert {
  margin-bottom: 20px;
}

.section {
  margin-bottom: 28px;
}

.section h3 {
  margin: 0 0 12px;
  font-size: 16px;
}

.section-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.section-head-row h3 {
  margin: 0;
}

.field-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.inline-hint {
  margin-left: 12px;
  margin-top: 0;
}

.discover-table,
.result-table {
  margin-top: 12px;
}

.job-progress-panel {
  margin: 16px 0;
  padding: 16px;
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

.job-eta {
  color: var(--el-text-color-secondary);
  font-weight: normal;
}

.job-stats,
.job-message {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.job-errors {
  margin-top: 8px;
  max-height: 120px;
  overflow: auto;
  font-size: 12px;
  color: var(--el-color-danger);
}

.job-error-line {
  padding: 2px 0;
}

.job-actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}

.subsection-title {
  margin: 20px 0 8px;
  font-size: 14px;
}

.job-history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.job-history-head .subsection-title {
  margin: 20px 0 8px;
}

.col-tag {
  margin: 2px 6px 2px 0;
  cursor: pointer;
}

.category-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.ml-8 {
  margin-left: 8px;
}

.run-form {
  flex-wrap: wrap;
}
</style>
