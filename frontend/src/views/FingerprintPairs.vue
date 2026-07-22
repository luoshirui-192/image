<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchImageBlob,
  getBlobCatalogObjectApi,
  listBlobCatalogConnectionsApi,
  listBlobCatalogDatabasesApi,
  listBlobCatalogObjectsApi,
} from '@/api/images'
import { useAuthStore } from '@/stores/auth'
import {
  cancelFingerprintImportJobApi,
  createFingerprintLayerTypeApi,
  deleteFingerprintPairApi,
  fetchFingerprintCompareApi,
  fetchFingerprintImportJobApi,
  fetchFingerprintLayerTypesApi,
  fetchFingerprintMetaApi,
  fetchFingerprintPairsApi,
  importFingerprintZipApi,
  updateFingerprintLayerTypeApi,
} from '@/api/fingerprints'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const compareLoading = ref(false)
const importing = ref(false)
const importJob = ref(null)
const pollTimer = ref(null)
const rows = ref([])
const total = ref(0)
const selectedPairId = ref(null)

const importDialogVisible = ref(false)
const importFile = ref(null)
const importVersion = ref('1.0')
const importFailOnDuplicates = ref(false)
const dupReportExpanded = ref(false)

const wbEnabled = ref(false)
const wbLoading = ref(false)
const wbConnections = ref([])
const wbDatabases = ref([])
const wbTables = ref([])
const wbColumns = ref([])
const wbConnectionKey = ref('')
const wbDatabase = ref('')
const wbTable = ref('')
const wbPersonColumn = ref('')
const wbFingerColumn = ref('')
const wbImageColumn = ref('')
const wbTemplateColumns = reactive({})

const selectedWbConnection = computed(() =>
  wbConnections.value.find((c) => connectionKey(c) === wbConnectionKey.value) || null,
)

const enabledLayerTypes = computed(() =>
  (meta.layer_types || []).filter((t) => t.enabled !== false && t.enabled !== 0),
)

const dupReport = computed(() => importJob.value?.duplicate_report || null)
const dupWarningRows = computed(() => {
  const list = dupReport.value?.warnings || []
  return list.slice(0, 50)
})

function connectionKey(conn) {
  if (!conn) return ''
  if (conn.connection_id != null) return `ext:${conn.connection_id}`
  return `alias:${conn.alias || 'default'}`
}

function catalogParams() {
  const conn = selectedWbConnection.value
  if (!conn) return {}
  if (conn.connection_id != null) return { connectionId: conn.connection_id }
  return { dbAlias: conn.alias || 'default' }
}

function resetWritebackForm() {
  wbEnabled.value = false
  wbDatabases.value = []
  wbTables.value = []
  wbColumns.value = []
  wbConnectionKey.value = ''
  wbDatabase.value = ''
  wbTable.value = ''
  wbPersonColumn.value = ''
  wbFingerColumn.value = ''
  wbImageColumn.value = ''
  Object.keys(wbTemplateColumns).forEach((k) => delete wbTemplateColumns[k])
}

async function ensureWbConnections() {
  if (wbConnections.value.length) return
  wbLoading.value = true
  try {
    const res = await listBlobCatalogConnectionsApi()
    wbConnections.value = res.data || []
    if (!wbConnectionKey.value && wbConnections.value.length) {
      wbConnectionKey.value = connectionKey(wbConnections.value[0])
    }
  } catch (err) {
    ElMessage.error(err.message || '加载数据库连接失败')
  } finally {
    wbLoading.value = false
  }
}

async function loadWbDatabases() {
  wbDatabases.value = []
  wbTables.value = []
  wbColumns.value = []
  wbDatabase.value = ''
  wbTable.value = ''
  if (!selectedWbConnection.value) return
  wbLoading.value = true
  try {
    const res = await listBlobCatalogDatabasesApi(catalogParams())
    wbDatabases.value = res.data?.databases || []
  } catch (err) {
    ElMessage.error(err.message || '加载数据库失败')
  } finally {
    wbLoading.value = false
  }
}

async function loadWbTables() {
  wbTables.value = []
  wbColumns.value = []
  wbTable.value = ''
  if (!wbDatabase.value) return
  wbLoading.value = true
  try {
    const res = await listBlobCatalogObjectsApi({
      ...catalogParams(),
      database: wbDatabase.value,
      objectType: 'table',
    })
    wbTables.value = res.data?.objects || []
  } catch (err) {
    ElMessage.error(err.message || '加载表失败')
  } finally {
    wbLoading.value = false
  }
}

async function loadWbColumns() {
  wbColumns.value = []
  wbPersonColumn.value = ''
  wbFingerColumn.value = ''
  wbImageColumn.value = ''
  Object.keys(wbTemplateColumns).forEach((k) => delete wbTemplateColumns[k])
  if (!wbDatabase.value || !wbTable.value) return
  wbLoading.value = true
  try {
    const res = await getBlobCatalogObjectApi(wbTable.value, {
      ...catalogParams(),
      database: wbDatabase.value,
    })
    wbColumns.value = res.data?.columns || []
  } catch (err) {
    ElMessage.error(err.message || '加载列失败')
  } finally {
    wbLoading.value = false
  }
}

function buildPathWritebackPayload() {
  if (!wbEnabled.value) return null
  if (!wbDatabase.value || !wbTable.value || !wbPersonColumn.value || !wbFingerColumn.value) {
    throw new Error('启用路径写回时请选择库、表、人员号列与指位列')
  }
  const templates = {}
  for (const lt of enabledLayerTypes.value) {
    const col = (wbTemplateColumns[lt.layer_key] || '').trim()
    if (col) templates[lt.layer_key] = col
  }
  const imageCol = (wbImageColumn.value || '').trim()
  if (!imageCol && !Object.keys(templates).length) {
    throw new Error('请至少指定图像路径列或一个模板路径列')
  }
  const conn = selectedWbConnection.value
  const payload = {
    enabled: true,
    database: wbDatabase.value,
    table: wbTable.value,
    match: {
      person_id_column: wbPersonColumn.value,
      finger_column: wbFingerColumn.value,
    },
    paths: {
      image_column: imageCol || undefined,
      templates,
    },
  }
  if (conn?.connection_id != null) {
    payload.connection_id = conn.connection_id
  } else {
    payload.db_alias = conn?.alias || 'default'
  }
  return payload
}

const typeDialogVisible = ref(false)
const typeLoading = ref(false)
const typeRows = ref([])
const typeForm = reactive({
  layer_key: '',
  label: '',
  color: '#43a047',
  suffixes: '',
  default_setlen: 0,
  default_setang: 256,
  sort_order: 100,
})

const meta = reactive({
  finger_positions: [],
  algo_versions: [],
  layer_types: [],
})

const filters = reactive({
  keyword: '',
  finger_position: '',
  batch_name: '',
  layer_type: '',
  algo_version: '',
  score_min: undefined,
  score_max: undefined,
})

const payload = ref(null)
const showLabels = ref(true)
const zoom = ref(1)
const versionMode = ref('overlay') // overlay | split
const leftTypes = ref([])
const rightTypes = ref([])
const selectedVersions = ref([])
const layersReady = ref(false)

const leftUrl = ref('')
const rightUrl = ref('')
const leftCanvas = ref(null)
const rightCanvas = ref(null)
const leftCanvasA = ref(null)
const leftCanvasB = ref(null)
const rightCanvasA = ref(null)
const rightCanvasB = ref(null)
const leftImg = ref(null)
const rightImg = ref(null)

const layerTypeLabel = computed(() => {
  const map = {}
  for (const item of meta.layer_types) {
    map[item.layer_key] = item.label || item.layer_key
  }
  return map
})

const checkboxOptions = computed(() => {
  const available = new Set(payload.value?.available_layer_types || [])
  const opts = (payload.value?.layer_type_options || []).filter((t) => available.has(t.layer_key))
  if (opts.length) return opts
  return [...available].map((key) => ({
    layer_key: key,
    label: layerTypeLabel.value[key] || key,
    color: '#888',
  }))
})

const availableVersions = computed(() => payload.value?.available_algo_versions || [])

/** In split mode use the first two checked versions (sorted). */
const splitVersions = computed(() => {
  const sorted = [...selectedVersions.value].sort()
  return sorted.slice(0, 2)
})

const selectedPair = computed(() => rows.value.find((r) => r.id === selectedPairId.value) || null)

const treeData = computed(() => {
  const groups = new Map()
  for (const row of rows.value) {
    const key = row.finger_position || 'unknown'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(row)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([position, items]) => ({
      id: `pos:${position}`,
      label: `${position}（${items.length}）`,
      isGroup: true,
      children: items.map((row) => ({
        id: `pair:${row.id}`,
        pairId: row.id,
        label: formatPairLabel(row),
        isGroup: false,
        row,
      })),
    }))
})

function formatPairLabel(row) {
  const score = row.match_score != null ? ` · ${row.match_score}` : ''
  const vers = (row.algo_versions || []).join('/')
  const verPart = vers ? ` [${vers}]` : ''
  return `${row.batch_name || `#${row.id}`}${score}${verPart}`
}

async function loadMeta() {
  const res = await fetchFingerprintMetaApi()
  meta.finger_positions = res.data.finger_positions || []
  meta.algo_versions = res.data.algo_versions || []
  meta.layer_types = res.data.layer_types || []
}

async function loadPairs() {
  loading.value = true
  try {
    const params = { page: 1, page_size: 500 }
    for (const key of ['keyword', 'finger_position', 'batch_name', 'layer_type', 'algo_version']) {
      if (filters[key]) params[key] = filters[key]
    }
    if (filters.score_min != null && filters.score_min !== '') params.score_min = filters.score_min
    if (filters.score_max != null && filters.score_max !== '') params.score_max = filters.score_max
    const res = await fetchFingerprintPairsApi(params)
    rows.value = res.data.items || []
    total.value = res.data.total || 0
    if (selectedPairId.value && !rows.value.some((r) => r.id === selectedPairId.value)) {
      selectedPairId.value = null
      clearCompare()
    }
  } catch (err) {
    ElMessage.error(err.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  loadPairs()
}

function onReset() {
  filters.keyword = ''
  filters.finger_position = ''
  filters.batch_name = ''
  filters.layer_type = ''
  filters.algo_version = ''
  filters.score_min = undefined
  filters.score_max = undefined
  loadPairs()
}

function onTreeNodeClick(data) {
  if (data.isGroup || !data.pairId) return
  selectPair(data.pairId)
}

function selectPair(pairId) {
  selectedPairId.value = Number(pairId)
  router.replace({ query: { ...route.query, id: String(pairId) } }).catch(() => {})
  loadCompare(Number(pairId))
}

function clearCompare() {
  payload.value = null
  layersReady.value = false
  leftTypes.value = []
  rightTypes.value = []
  selectedVersions.value = []
  revokeUrls()
  leftImg.value = null
  rightImg.value = null
}

async function onDeleteSelected() {
  const row = selectedPair.value
  if (!row) return
  try {
    await ElMessageBox.confirm(`确认删除配对 ${row.batch_name}？`, '删除确认', { type: 'warning' })
    await deleteFingerprintPairApi(row.id)
    ElMessage.success('已删除')
    selectedPairId.value = null
    clearCompare()
    await loadPairs()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '删除失败')
  }
}

function stopPoll() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

async function pollImportJob(jobId) {
  if (jobId == null) {
    stopPoll()
    importing.value = false
    return
  }
  try {
    const res = await fetchFingerprintImportJobApi(jobId)
    const job = res?.data
    if (!job || typeof job !== 'object') {
      stopPoll()
      importing.value = false
      ElMessage.error('导入进度接口返回异常')
      return
    }
    importJob.value = job
    const status = job.status
    if (status === 'completed' || status === 'failed' || status === 'cancelled') {
      stopPoll()
      importing.value = false
      const dupTotal = Number(job.duplicate_report?.total || 0)
      if (dupTotal > 0) dupReportExpanded.value = true
      if (status === 'completed') {
        if (dupTotal > 0) ElMessage.warning(job.message || `导入完成，发现 ${dupTotal} 项重复`)
        else ElMessage.success(job.message || '导入完成')
      } else if (status === 'failed') ElMessage.error(job.message || job.last_error || '导入失败')
      else ElMessage.warning(job.message || '已取消')
      await loadMeta()
      await loadPairs()
      if (selectedPairId.value) await loadCompare(selectedPairId.value)
    }
  } catch (err) {
    stopPoll()
    importing.value = false
    ElMessage.error(err.message || '查询导入进度失败')
  }
}

function openImportDialog() {
  importFile.value = null
  importVersion.value = '1.0'
  importFailOnDuplicates.value = false
  resetWritebackForm()
  importDialogVisible.value = true
  ensureWbConnections()
}

watch(wbEnabled, (on) => {
  if (on) ensureWbConnections().then(() => {
    if (wbConnectionKey.value && !wbDatabases.value.length) loadWbDatabases()
  })
})

watch(wbConnectionKey, () => {
  if (wbEnabled.value) loadWbDatabases()
})

watch(wbDatabase, () => {
  if (wbEnabled.value) loadWbTables()
})

watch(wbTable, () => {
  if (wbEnabled.value) loadWbColumns()
})

function dupTypeLabel(type) {
  const map = {
    zip_duplicate_content: '包内同内容',
    zip_name_collision: '同名覆盖',
    pair_same_bmp: '左右同图',
    cross_pair_shared_bmp: '跨配对共用',
  }
  return map[type] || type
}

function onImportFileChange(uploadFile) {
  importFile.value = uploadFile.raw || null
}

async function submitImport() {
  if (!importFile.value) {
    ElMessage.warning('请选择 zip 文件')
    return
  }
  const ver = (importVersion.value || '').trim()
  if (!ver) {
    ElMessage.warning('请填写算法版本')
    return
  }
  let pathWriteback = null
  try {
    pathWriteback = buildPathWritebackPayload()
  } catch (err) {
    ElMessage.warning(err.message || '路径写回配置不完整')
    return
  }
  importing.value = true
  importJob.value = null
  importDialogVisible.value = false
  stopPoll()
  try {
    const res = await importFingerprintZipApi(importFile.value, {
      algo_version: ver,
      skip_existing: true,
      fail_on_duplicates: importFailOnDuplicates.value,
      path_writeback: pathWriteback,
    })
    const job = res?.data?.job
    if (!job?.id) {
      importing.value = false
      ElMessage.error('未拿到导入任务')
      return
    }
    importJob.value = job
    dupReportExpanded.value = false
    ElMessage.success(
      pathWriteback
        ? `已启动导入（版本 ${ver}，含路径写回）`
        : `已启动导入（版本 ${ver}）：已有配对会合并新版本特征层`,
    )
    await pollImportJob(job.id)
    if (importing.value) {
      pollTimer.value = setInterval(() => pollImportJob(job.id), 1500)
    }
  } catch (err) {
    importing.value = false
    ElMessage.error(err.message || '导入失败')
  }
}

async function onCancelImport() {
  if (!importJob.value?.id) return
  try {
    await cancelFingerprintImportJobApi(importJob.value.id)
    ElMessage.info('已请求取消')
  } catch (err) {
    ElMessage.error(err.message || '取消失败')
  }
}

async function openTypeDialog() {
  typeDialogVisible.value = true
  await loadTypeRows()
}

async function loadTypeRows() {
  typeLoading.value = true
  try {
    const res = await fetchFingerprintLayerTypesApi({ enabled_only: '0' })
    typeRows.value = res.data.items || []
  } catch (err) {
    ElMessage.error(err.message || '加载特征类型失败')
  } finally {
    typeLoading.value = false
  }
}

async function submitNewType() {
  if (!auth.isAdmin) {
    ElMessage.error('仅管理员可新增')
    return
  }
  const key = (typeForm.layer_key || '').trim().toLowerCase()
  const suffixes = (typeForm.suffixes || key).trim().toLowerCase()
  if (!key || !suffixes) {
    ElMessage.warning('layer_key 与 suffixes 必填')
    return
  }
  try {
    await createFingerprintLayerTypeApi({
      layer_key: key,
      label: typeForm.label || key,
      color: typeForm.color || '#888888',
      suffixes,
      default_setlen: Number(typeForm.default_setlen) || 0,
      default_setang: Number(typeForm.default_setang) || 256,
      sort_order: Number(typeForm.sort_order) || 100,
    })
    ElMessage.success('已新增特征类型')
    typeForm.layer_key = ''
    typeForm.label = ''
    typeForm.suffixes = ''
    await loadTypeRows()
    await loadMeta()
  } catch (err) {
    ElMessage.error(err.message || '新增失败')
  }
}

async function toggleTypeEnabled(row) {
  if (!auth.isAdmin) return
  try {
    await updateFingerprintLayerTypeApi(row.id, { enabled: !row.enabled })
    await loadTypeRows()
    await loadMeta()
  } catch (err) {
    ElMessage.error(err.message || '更新失败')
  }
}

function revokeUrls() {
  if (leftUrl.value) URL.revokeObjectURL(leftUrl.value)
  if (rightUrl.value) URL.revokeObjectURL(rightUrl.value)
  leftUrl.value = ''
  rightUrl.value = ''
}

async function loadCompare(pairId) {
  if (!pairId) return
  compareLoading.value = true
  layersReady.value = false
  try {
    const res = await fetchFingerprintCompareApi(pairId, { show_labels: '1' })
    payload.value = res.data
    leftTypes.value = [...(res.data.available_layer_types || [])]
    rightTypes.value = [...(res.data.available_layer_types || [])]
    selectedVersions.value = [...(res.data.available_algo_versions || [])]
    if (selectedVersions.value.length >= 2) {
      versionMode.value = versionMode.value || 'overlay'
    }
    layersReady.value = true

    revokeUrls()
    const leftBlob = await fetchImageBlob(res.data.left.image_path, {
      id: res.data.left.image_id,
      thumb: false,
    })
    const rightBlob = await fetchImageBlob(res.data.right.image_path, {
      id: res.data.right.image_id,
      thumb: false,
    })
    leftUrl.value = URL.createObjectURL(leftBlob)
    rightUrl.value = URL.createObjectURL(rightBlob)
    await nextTick()
    await drawBoth()
  } catch (err) {
    clearCompare()
    ElMessage.error(err.message || '加载对比失败')
  } finally {
    compareLoading.value = false
  }
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = url
  })
}

function layerVisible(layer, side, versionFilter) {
  const types = side === 'left' ? leftTypes.value : rightTypes.value
  if (!types.includes(layer.layer_type)) return false
  if (versionFilter != null) {
    return layer.algo_version === versionFilter
  }
  if (selectedVersions.value.length && !selectedVersions.value.includes(layer.algo_version)) {
    return false
  }
  return true
}

function drawSide(canvasEl, imgEl, side, versionFilter = null) {
  if (!canvasEl || !imgEl || !payload.value) return
  const layers = (payload.value.layers || []).filter(
    (l) => l.side === side && layerVisible(l, side, versionFilter),
  )
  const width = imgEl.naturalWidth || imgEl.width
  const height = imgEl.naturalHeight || imgEl.height
  const scale = zoom.value
  canvasEl.width = Math.round(width * scale)
  canvasEl.height = Math.round(height * scale)
  const ctx = canvasEl.getContext('2d')
  ctx.clearRect(0, 0, canvasEl.width, canvasEl.height)
  ctx.imageSmoothingEnabled = false
  ctx.drawImage(imgEl, 0, 0, canvasEl.width, canvasEl.height)

  const arrowLen = 12 * scale
  for (const layer of layers) {
    const color = layer.color || '#e53935'
    const minutiae = layer.minutiae?.minutiae || []
    for (const m of minutiae) {
      const x = m.x * scale
      const y = m.y * scale
      const rad = ((m.d || 0) * Math.PI) / 180
      ctx.beginPath()
      ctx.arc(x, y, 2.2 * scale, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.lineTo(x + Math.cos(rad) * arrowLen, y - Math.sin(rad) * arrowLen)
      ctx.strokeStyle = color
      ctx.lineWidth = Math.max(1, scale)
      ctx.stroke()
      if (showLabels.value && m.index != null) {
        ctx.fillStyle = '#111'
        ctx.font = `${Math.max(9, 10 * scale)}px sans-serif`
        ctx.fillText(String(m.index), x + 3 * scale, y - 3 * scale)
      }
    }
  }
}

async function drawBoth() {
  if (!leftUrl.value || !rightUrl.value) return
  leftImg.value = await loadImage(leftUrl.value)
  rightImg.value = await loadImage(rightUrl.value)
  await nextTick()
  redrawBoth()
}

function redrawBoth() {
  if (!leftImg.value || !rightImg.value) return
  if (versionMode.value === 'split' && splitVersions.value.length >= 2) {
    const [va, vb] = splitVersions.value
    drawSide(leftCanvasA.value, leftImg.value, 'left', va)
    drawSide(leftCanvasB.value, leftImg.value, 'left', vb)
    drawSide(rightCanvasA.value, rightImg.value, 'right', va)
    drawSide(rightCanvasB.value, rightImg.value, 'right', vb)
  } else {
    drawSide(leftCanvas.value, leftImg.value, 'left', null)
    drawSide(rightCanvas.value, rightImg.value, 'right', null)
  }
}

watch([leftTypes, rightTypes, selectedVersions, showLabels, zoom, versionMode], async () => {
  if (!layersReady.value) return
  await nextTick()
  redrawBoth()
})

onMounted(async () => {
  await loadMeta()
  await loadPairs()
  const qid = Number(route.query.id || route.params.id)
  if (qid) {
    selectedPairId.value = qid
    await loadCompare(qid)
  }
})

onBeforeUnmount(() => {
  stopPoll()
  revokeUrls()
})
</script>

<template>
  <div class="fp-page">
    <div class="fp-toolbar">
      <div class="fp-title">
        <h2>指纹成对对比</h2>
        <p>左树选配对 · 右栏对比 · 支持多特征类型与多算法版本</p>
      </div>
      <div class="import-actions">
        <el-button v-if="auth.isAdmin" @click="openTypeDialog">特征类型</el-button>
        <el-button type="primary" :loading="importing" @click="openImportDialog">导入 zip</el-button>
        <el-button v-if="importing && importJob" @click="onCancelImport">取消导入</el-button>
      </div>
    </div>

    <el-card v-if="importJob" shadow="never" class="import-progress">
      <div class="import-progress-head">
        <strong>{{ importJob.zip_name || '导入任务' }}</strong>
        <span>{{ importJob.status }} · {{ importJob.message }}</span>
      </div>
      <el-progress
        :percentage="Number(importJob.percent || 0)"
        :status="importJob.status === 'failed' ? 'exception' : (importJob.status === 'completed' ? 'success' : undefined)"
      />
      <div class="import-progress-meta">
        进度 {{ importJob.processed || 0 }}/{{ importJob.total_estimate || '?' }}
        · 成功 {{ importJob.succeeded || 0 }}
        · 跳过 {{ importJob.skipped || 0 }}
        · 失败 {{ importJob.failed || 0 }}
        <template v-if="importJob.library_bmp_reused">
          · 图库复用 bmp {{ importJob.library_bmp_reused }}
        </template>
        <template v-if="importJob.path_writeback_enabled">
          · 路径写回 更新 {{ importJob.writeback_updated || 0 }}
          / 跳过 {{ importJob.writeback_skipped || 0 }}
          / 失败 {{ importJob.writeback_failed || 0 }}
        </template>
      </div>
      <div
        v-if="importJob.path_writeback_enabled && (importJob.writeback_errors || []).length"
        class="dup-report"
      >
        <div class="muted">写回错误样例：</div>
        <ul class="wb-errors">
          <li v-for="(err, idx) in (importJob.writeback_errors || []).slice(0, 8)" :key="idx">{{ err }}</li>
        </ul>
      </div>
      <div v-if="dupReport && dupReport.total > 0" class="dup-report">
        <div class="dup-report-head">
          <el-tag type="warning" size="small">重复检测</el-tag>
          <span>{{ dupReport.summary }}</span>
          <el-button link type="primary" size="small" @click="dupReportExpanded = !dupReportExpanded">
            {{ dupReportExpanded ? '收起' : '展开明细' }}
          </el-button>
        </div>
        <div v-if="dupReportExpanded" class="dup-report-body">
          <div v-for="(w, idx) in dupWarningRows" :key="idx" class="dup-row">
            <el-tag size="small" effect="plain">{{ dupTypeLabel(w.type) }}</el-tag>
            <span>{{ w.message }}</span>
            <span v-if="w.paths?.length" class="dup-paths">{{ w.paths.slice(0, 4).join(' · ') }}</span>
          </div>
          <div v-if="(dupReport.warnings || []).length > dupWarningRows.length" class="muted">
            仅显示前 {{ dupWarningRows.length }} 条
          </div>
        </div>
      </div>
    </el-card>

    <div class="layout">
      <aside class="tree-panel" v-loading="loading">
        <div class="panel-head">
          <strong>配对目录</strong>
          <span class="muted">共 {{ total }} 对</span>
        </div>
        <div class="filter-box">
          <el-input v-model="filters.keyword" clearable size="small" placeholder="关键词" @keyup.enter="onSearch" />
          <el-select v-model="filters.finger_position" clearable size="small" placeholder="指位" style="width: 100%">
            <el-option v-for="p in meta.finger_positions" :key="p" :label="p" :value="p" />
          </el-select>
          <el-select v-model="filters.layer_type" clearable size="small" placeholder="特征层" style="width: 100%">
            <el-option v-for="t in meta.layer_types" :key="t.layer_key" :label="t.label" :value="t.layer_key" />
          </el-select>
          <el-select v-model="filters.algo_version" clearable size="small" placeholder="算法版本" style="width: 100%">
            <el-option v-for="v in meta.algo_versions" :key="v" :label="v" :value="v" />
          </el-select>
          <div class="score-row">
            <el-input-number v-model="filters.score_min" :controls="false" size="small" placeholder="分min" style="width: 100%" />
            <span>~</span>
            <el-input-number v-model="filters.score_max" :controls="false" size="small" placeholder="分max" style="width: 100%" />
          </div>
          <div class="filter-actions">
            <el-button type="primary" size="small" @click="onSearch">筛选</el-button>
            <el-button size="small" @click="onReset">重置</el-button>
          </div>
        </div>
        <div class="tree-wrap">
          <el-tree
            v-if="treeData.length"
            :data="treeData"
            node-key="id"
            default-expand-all
            highlight-current
            :expand-on-click-node="false"
            @node-click="onTreeNodeClick"
          />
          <el-empty v-else description="暂无配对，请先导入 zip" :image-size="64" />
        </div>
        <div v-if="selectedPair" class="selection-foot">
          <div class="sel-title">{{ selectedPair.batch_name }}</div>
          <div class="sel-meta">
            {{ selectedPair.finger_position }}
            <template v-if="selectedPair.match_score != null"> · score {{ selectedPair.match_score }}</template>
            <template v-if="selectedPair.algo_versions?.length"> · ver {{ selectedPair.algo_versions.join(', ') }}</template>
          </div>
          <el-button size="small" type="danger" plain @click="onDeleteSelected">删除此配对</el-button>
        </div>
      </aside>

      <main class="compare-panel" v-loading="compareLoading">
        <template v-if="payload">
          <div class="compare-toolbar">
            <div class="meta">
              {{ payload.pair.batch_name }} · {{ payload.pair.finger_position }}
              <template v-if="payload.pair.match_score != null"> · score {{ payload.pair.match_score }}</template>
            </div>
            <div class="controls">
              <span class="label">版本对比</span>
              <el-radio-group v-model="versionMode" size="small">
                <el-radio-button value="overlay">叠色</el-radio-button>
                <el-radio-button value="split" :disabled="availableVersions.length < 2">分列</el-radio-button>
              </el-radio-group>
              <span class="label">版本</span>
              <el-checkbox-group v-model="selectedVersions">
                <el-checkbox v-for="v in availableVersions" :key="v" :label="v" :value="v">{{ v }}</el-checkbox>
              </el-checkbox-group>
              <el-checkbox v-model="showLabels">编号</el-checkbox>
              <span class="label">缩放</span>
              <el-slider v-model="zoom" :min="0.5" :max="3" :step="0.1" style="width: 120px" />
            </div>
            <div v-if="versionMode === 'split'" class="hint">
              分列模式使用已勾选版本中的前两个：{{ splitVersions.join(' | ') || '请至少勾选两个版本' }}
            </div>
          </div>

          <div class="compare-grid">
            <!-- LEFT sample -->
            <div class="pane">
              <div class="pane-title">{{ payload.left.image_name }}</div>
              <div v-if="versionMode === 'overlay'" class="canvas-wrap">
                <canvas ref="leftCanvas" />
              </div>
              <div v-else class="split-wrap">
                <div class="split-col">
                  <div class="split-label">ver {{ splitVersions[0] || '-' }}</div>
                  <div class="canvas-wrap">
                    <canvas ref="leftCanvasA" />
                  </div>
                </div>
                <div class="split-col">
                  <div class="split-label">ver {{ splitVersions[1] || '-' }}</div>
                  <div class="canvas-wrap">
                    <canvas ref="leftCanvasB" />
                  </div>
                </div>
              </div>
              <div class="pane-layers">
                <span class="label">本侧特征层</span>
                <el-checkbox-group v-model="leftTypes">
                  <el-checkbox
                    v-for="opt in checkboxOptions"
                    :key="`L-${opt.layer_key}`"
                    :label="opt.layer_key"
                    :value="opt.layer_key"
                  >
                    <span class="swatch" :style="{ background: opt.color }" />
                    {{ opt.label || opt.layer_key }}
                  </el-checkbox>
                </el-checkbox-group>
              </div>
            </div>

            <!-- RIGHT sample -->
            <div class="pane">
              <div class="pane-title">{{ payload.right.image_name }}</div>
              <div v-if="versionMode === 'overlay'" class="canvas-wrap">
                <canvas ref="rightCanvas" />
              </div>
              <div v-else class="split-wrap">
                <div class="split-col">
                  <div class="split-label">ver {{ splitVersions[0] || '-' }}</div>
                  <div class="canvas-wrap">
                    <canvas ref="rightCanvasA" />
                  </div>
                </div>
                <div class="split-col">
                  <div class="split-label">ver {{ splitVersions[1] || '-' }}</div>
                  <div class="canvas-wrap">
                    <canvas ref="rightCanvasB" />
                  </div>
                </div>
              </div>
              <div class="pane-layers">
                <span class="label">本侧特征层</span>
                <el-checkbox-group v-model="rightTypes">
                  <el-checkbox
                    v-for="opt in checkboxOptions"
                    :key="`R-${opt.layer_key}`"
                    :label="opt.layer_key"
                    :value="opt.layer_key"
                  >
                    <span class="swatch" :style="{ background: opt.color }" />
                    {{ opt.label || opt.layer_key }}
                  </el-checkbox>
                </el-checkbox-group>
              </div>
            </div>
          </div>
        </template>
        <el-empty v-else description="请在左侧树中选择一对指纹" />
      </main>
    </div>

    <!-- Import dialog -->
    <el-dialog v-model="importDialogVisible" title="导入 batmatch zip" width="640px">
      <p class="dialog-tip">
        同一配对再次导入时，若填写<strong>新的算法版本</strong>，会把该版本特征层合并进已有配对，用于版本对比；
        相同版本已存在的层会跳过。
      </p>
      <el-form label-width="110px" v-loading="wbLoading">
        <el-form-item label="算法版本" required>
          <el-input v-model="importVersion" placeholder="例如 1.0 / 2.0 / bidiso-2024" />
        </el-form-item>
        <el-form-item label="zip 文件" required>
          <el-upload :auto-upload="false" :show-file-list="true" :limit="1" accept=".zip" :on-change="onImportFileChange">
            <el-button>选择文件</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="严格模式">
          <el-checkbox v-model="importFailOnDuplicates">
            发现左右同图 / 同名覆盖时中止导入
          </el-checkbox>
        </el-form-item>

        <el-divider content-position="left">路径写回（可选）</el-divider>
        <p class="dialog-tip">
          导入成功后，把 MinIO 相对路径 UPDATE 到业务表；按文件名中的人员号 + 指位匹配行。
        </p>
        <el-form-item label="启用写回">
          <el-switch v-model="wbEnabled" />
        </el-form-item>
        <template v-if="wbEnabled">
          <el-form-item label="数据库连接" required>
            <el-select v-model="wbConnectionKey" filterable placeholder="选择连接" style="width: 100%">
              <el-option
                v-for="conn in wbConnections"
                :key="connectionKey(conn)"
                :label="conn.label || conn.alias"
                :value="connectionKey(conn)"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="数据库" required>
            <el-select v-model="wbDatabase" filterable placeholder="选择库" style="width: 100%">
              <el-option v-for="db in wbDatabases" :key="db.name" :label="db.name" :value="db.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标表" required>
            <el-select v-model="wbTable" filterable placeholder="选择表" style="width: 100%">
              <el-option
                v-for="obj in wbTables"
                :key="obj.name"
                :label="obj.name"
                :value="obj.name"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="人员号列" required>
            <el-select v-model="wbPersonColumn" filterable clearable placeholder="匹配 personId" style="width: 100%">
              <el-option v-for="col in wbColumns" :key="`p-${col.name}`" :label="col.name" :value="col.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="指位列" required>
            <el-select v-model="wbFingerColumn" filterable clearable placeholder="匹配 right_index 等" style="width: 100%">
              <el-option v-for="col in wbColumns" :key="`f-${col.name}`" :label="col.name" :value="col.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="图像路径列">
            <el-select v-model="wbImageColumn" filterable clearable placeholder="写入 bmp 相对路径" style="width: 100%">
              <el-option v-for="col in wbColumns" :key="`i-${col.name}`" :label="col.name" :value="col.name" />
            </el-select>
          </el-form-item>
          <el-form-item
            v-for="lt in enabledLayerTypes"
            :key="`tpl-${lt.layer_key}`"
            :label="`${lt.label || lt.layer_key} 路径`"
          >
            <el-select
              v-model="wbTemplateColumns[lt.layer_key]"
              filterable
              clearable
              :placeholder="`写入 ${lt.layer_key} 模板路径`"
              style="width: 100%"
            >
              <el-option v-for="col in wbColumns" :key="`${lt.layer_key}-${col.name}`" :label="col.name" :value="col.name" />
            </el-select>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitImport">开始导入</el-button>
      </template>
    </el-dialog>

    <!-- Layer type management -->
    <el-dialog v-model="typeDialogVisible" title="特征类型配置" width="720px" @opened="loadTypeRows">
      <p class="dialog-tip">新增类型后，导入带对应后缀的模板即可在勾选框中出现（扩到约 6 种无需改页面结构）。</p>
      <el-table v-loading="typeLoading" :data="typeRows" size="small" border>
        <el-table-column prop="layer_key" label="key" width="110" />
        <el-table-column prop="label" label="显示名" width="110" />
        <el-table-column prop="suffixes" label="后缀" min-width="120" />
        <el-table-column label="颜色" width="80">
          <template #default="{ row }">
            <span class="swatch" :style="{ background: row.color }" /> {{ row.color }}
          </template>
        </el-table-column>
        <el-table-column prop="default_setlen" label="setlen" width="70" />
        <el-table-column prop="default_setang" label="setang" width="70" />
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch
              :model-value="!!row.enabled"
              :disabled="!auth.isAdmin"
              @change="toggleTypeEnabled(row)"
            />
          </template>
        </el-table-column>
      </el-table>

      <el-divider v-if="auth.isAdmin">新增类型</el-divider>
      <el-form v-if="auth.isAdmin" :inline="true" size="small">
        <el-form-item label="key">
          <el-input v-model="typeForm.layer_key" style="width: 100px" placeholder="customiso" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="typeForm.label" style="width: 100px" />
        </el-form-item>
        <el-form-item label="后缀">
          <el-input v-model="typeForm.suffixes" style="width: 100px" placeholder="customiso" />
        </el-form-item>
        <el-form-item label="颜色">
          <el-color-picker v-model="typeForm.color" />
        </el-form-item>
        <el-form-item label="setlen">
          <el-input-number v-model="typeForm.default_setlen" :controls="false" style="width: 70px" />
        </el-form-item>
        <el-form-item label="setang">
          <el-input-number v-model="typeForm.default_setang" :controls="false" style="width: 70px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submitNewType">添加</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>

<style scoped>
.fp-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 120px);
  min-height: 520px;
}
.fp-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-shrink: 0;
}
.fp-title h2 {
  margin: 0 0 4px;
  font-size: 20px;
}
.fp-title p {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.import-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.import-progress { flex-shrink: 0; }
.import-progress-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
}
.import-progress-meta {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.dup-report {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
}
.dup-report-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.dup-report-body {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 180px;
  overflow: auto;
}
.dup-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}
.dup-paths {
  color: var(--el-text-color-secondary);
  word-break: break-all;
}
.layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 12px;
  flex: 1;
  min-height: 0;
}
.tree-panel,
.compare-panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color);
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.wb-errors {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--el-color-danger);
}
.filter-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.score-row {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 6px;
  align-items: center;
}
.filter-actions { display: flex; gap: 8px; }
.tree-wrap { flex: 1; overflow: auto; padding: 8px 4px; }
.selection-foot {
  padding: 10px 12px;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sel-title { font-size: 13px; font-weight: 600; word-break: break-all; }
.sel-meta { font-size: 12px; color: var(--el-text-color-secondary); }
.compare-toolbar {
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}
.meta { font-size: 13px; }
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
}
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.label { color: var(--el-text-color-secondary); font-size: 12px; }
.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  min-height: 0;
}
.pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--el-border-color-lighter);
  background: #f7f7f7;
}
.pane:last-child { border-right: none; }
.pane-title {
  padding: 8px 12px;
  font-size: 12px;
  background: #fff;
  border-bottom: 1px solid var(--el-border-color-lighter);
  word-break: break-all;
  flex-shrink: 0;
}
.canvas-wrap {
  flex: 1;
  overflow: auto;
  padding: 8px;
  text-align: center;
  min-height: 0;
}
.split-wrap {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.split-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px dashed var(--el-border-color-lighter);
}
.split-col:last-child { border-right: none; }
.split-label {
  padding: 4px 8px;
  font-size: 11px;
  background: #fff;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  color: var(--el-text-color-secondary);
}
.pane-layers {
  flex-shrink: 0;
  padding: 8px 12px;
  background: #fff;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
  vertical-align: middle;
}
.dialog-tip {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
canvas {
  max-width: none;
  background: #fff;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.06);
}
@media (max-width: 960px) {
  .layout { grid-template-columns: 1fr; }
  .compare-grid { grid-template-columns: 1fr; }
}
</style>
