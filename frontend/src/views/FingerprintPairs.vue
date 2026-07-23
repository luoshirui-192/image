<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchImageBlob,
  listBlobCatalogConnectionsApi,
} from '@/api/images'
import { useAuthStore } from '@/stores/auth'
import {
  cancelFingerprintImportJobApi,
  createFingerprintLayerTypeApi,
  fetchFingerprintBizMetaApi,
  fetchFingerprintBizSampleViewApi,
  fetchFingerprintBizSamplesApi,
  fetchFingerprintImportJobApi,
  fetchFingerprintLayerTypesApi,
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
const selectedCapId = ref(null)

const importDialogVisible = ref(false)
const importFile = ref(null)
const importVersion = ref('1.0')
const importFailOnDuplicates = ref(false)
const dupReportExpanded = ref(false)

const wbEnabled = ref(false)
const wbLoading = ref(false)
const wbConnections = ref([])
const wbConnectionKey = ref('')

/** Browse connection (same catalog as writeback). */
const browseConnectionKey = ref('')
const browseLoading = ref(false)

const selectedWbConnection = computed(() =>
  wbConnections.value.find((c) => connectionKey(c) === wbConnectionKey.value) || null,
)
const selectedBrowseConnection = computed(() =>
  wbConnections.value.find((c) => connectionKey(c) === browseConnectionKey.value) || null,
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

function connectionQueryParams(conn) {
  if (!conn) return null
  const params = { database: 'ara_fp_analyst' }
  if (conn.connection_id != null) {
    params.connection_id = conn.connection_id
  } else {
    params.db_alias = conn.alias || 'default'
    // Local/default alias: leave database empty so sqlite tests / same-DB work.
    if (!conn.connection_id && (conn.alias === 'default' || !conn.alias)) {
      params.database = ''
    }
  }
  return params
}

function resetWritebackForm() {
  wbEnabled.value = false
  wbConnectionKey.value = ''
}

async function ensureConnections() {
  if (wbConnections.value.length) return
  wbLoading.value = true
  browseLoading.value = true
  try {
    const res = await listBlobCatalogConnectionsApi()
    wbConnections.value = res.data || []
    const preferred = wbConnections.value.find((c) =>
      String(c.label || c.alias || '').toLowerCase().includes('ara')
      || String(c.name || '').toLowerCase().includes('ara'),
    )
    const fallback = preferred || wbConnections.value[0]
    if (fallback) {
      const key = connectionKey(fallback)
      if (!browseConnectionKey.value) browseConnectionKey.value = key
      if (!wbConnectionKey.value) wbConnectionKey.value = key
    }
  } catch (err) {
    ElMessage.error(err.message || '加载数据库连接失败')
  } finally {
    wbLoading.value = false
    browseLoading.value = false
  }
}

function buildPathWritebackPayload() {
  if (!wbEnabled.value) return null
  const conn = selectedWbConnection.value
  if (!conn) {
    throw new Error('启用路径写回时请选择数据库连接（需能访问 ara_fp_analyst）')
  }
  const payload = {
    enabled: true,
    database: 'ara_fp_analyst',
    dataset_code: 'PK_5W',
  }
  if (conn.connection_id != null) {
    payload.connection_id = conn.connection_id
  } else {
    payload.db_alias = conn.alias || 'default'
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
  dataset_codes: [],
  layer_types: [],
})

const filters = reactive({
  keyword: '',
  dataset_code: '',
})

const payload = ref(null)
const showLabels = ref(true)
const zoom = ref(1)
const panelTypes = ref([]) // layer_type keys checked for primary panel
const layersReady = ref(false)

const panelUrls = ref([]) // object URLs per panel
const panelCanvases = ref([]) // canvas refs via function
const panelImgs = ref([])

const panels = computed(() => payload.value?.panels || [])
const primaryPanel = computed(() => panels.value[0] || null)

const treeData = computed(() => {
  const groups = new Map()
  for (const row of rows.value) {
    const key = row.dataset_code || 'unknown'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(row)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([dataset, items]) => ({
      id: `ds:${dataset}`,
      label: `${dataset}（${items.length}）`,
      isGroup: true,
      children: items.map((row) => ({
        id: `cap:${row.cap_image_id}`,
        capImageId: row.cap_image_id,
        label: row.cap_image_id,
        isGroup: false,
        row,
      })),
    }))
})

const checkboxOptions = computed(() => {
  const available = new Set(primaryPanel.value?.available_layer_types || payload.value?.available_layer_types || [])
  const opts = (payload.value?.layer_type_options || meta.layer_types || []).filter((t) =>
    available.has(t.layer_key),
  )
  if (opts.length) return opts
  return [...available].map((key) => ({
    layer_key: key,
    label: key,
    color: '#888',
  }))
})

function setCanvasRef(idx, el) {
  panelCanvases.value[idx] = el
}

async function loadMeta() {
  const conn = selectedBrowseConnection.value
  const params = connectionQueryParams(conn)
  if (!params) {
    meta.dataset_codes = []
    meta.layer_types = []
    return
  }
  try {
    const res = await fetchFingerprintBizMetaApi(params)
    meta.dataset_codes = res.data.dataset_codes || []
    meta.layer_types = res.data.layer_types || []
  } catch (err) {
    ElMessage.error(err.message || '加载业务表元数据失败')
  }
}

async function loadSamples() {
  const conn = selectedBrowseConnection.value
  const params = connectionQueryParams(conn)
  if (!params) {
    rows.value = []
    total.value = 0
    return
  }
  loading.value = true
  try {
    const q = {
      ...params,
      page: 1,
      page_size: 500,
    }
    if (filters.keyword) q.keyword = filters.keyword
    if (filters.dataset_code) q.dataset_code = filters.dataset_code
    const res = await fetchFingerprintBizSamplesApi(q)
    rows.value = res.data.items || []
    total.value = res.data.total || 0
    if (selectedCapId.value && !rows.value.some((r) => r.cap_image_id === selectedCapId.value)) {
      selectedCapId.value = null
      clearView()
    }
  } catch (err) {
    ElMessage.error(err.message || '加载业务样本失败')
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function onSearch() {
  loadSamples()
}

function onReset() {
  filters.keyword = ''
  filters.dataset_code = ''
  loadSamples()
}

function onTreeNodeClick(data) {
  if (data.isGroup || !data.capImageId) return
  selectSample(data.capImageId)
}

function selectSample(capImageId) {
  selectedCapId.value = String(capImageId)
  router.replace({ query: { ...route.query, cap: String(capImageId) } }).catch(() => {})
  loadView(String(capImageId))
}

function clearView() {
  payload.value = null
  layersReady.value = false
  panelTypes.value = []
  revokeUrls()
  panelImgs.value = []
}

function revokeUrls() {
  for (const url of panelUrls.value) {
    if (url) URL.revokeObjectURL(url)
  }
  panelUrls.value = []
}

async function loadView(capImageId) {
  if (!capImageId) return
  const conn = selectedBrowseConnection.value
  const params = connectionQueryParams(conn)
  if (!params) {
    ElMessage.warning('请先选择能访问 ara_fp_analyst 的数据库连接')
    return
  }
  compareLoading.value = true
  layersReady.value = false
  try {
    const res = await fetchFingerprintBizSampleViewApi(capImageId, {
      ...params,
      show_labels: '1',
    })
    payload.value = res.data
    const types = res.data.available_layer_types || res.data.panels?.[0]?.available_layer_types || []
    panelTypes.value = [...types]
    layersReady.value = true

    revokeUrls()
    const urls = []
    for (const panel of res.data.panels || []) {
      const path = panel.image?.path
      if (!path) {
        urls.push('')
        continue
      }
      if (panel.image?.error) {
        ElMessage.warning(`${panel.cap_image_id}: ${panel.image.error}`)
      }
      try {
        const blob = await fetchImageBlob(path, { thumb: false })
        urls.push(URL.createObjectURL(blob))
      } catch (err) {
        urls.push('')
        ElMessage.error(err.message || `加载图像失败: ${path}`)
      }
    }
    panelUrls.value = urls
    await nextTick()
    await drawPanels()
  } catch (err) {
    clearView()
    ElMessage.error(err.message || '加载样本失败')
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

function layerVisible(layer) {
  return panelTypes.value.includes(layer.layer_type)
}

function drawPanel(canvasEl, imgEl, panel) {
  if (!canvasEl || !imgEl || !panel) return
  const layers = (panel.layers || []).filter(layerVisible)
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

async function drawPanels() {
  const imgs = []
  for (let i = 0; i < panelUrls.value.length; i += 1) {
    const url = panelUrls.value[i]
    if (!url) {
      imgs[i] = null
      continue
    }
    imgs[i] = await loadImage(url)
  }
  panelImgs.value = imgs
  await nextTick()
  redrawPanels()
}

function redrawPanels() {
  for (let i = 0; i < panels.value.length; i += 1) {
    drawPanel(panelCanvases.value[i], panelImgs.value[i], panels.value[i])
  }
}

watch([panelTypes, showLabels, zoom], async () => {
  if (!layersReady.value) return
  await nextTick()
  redrawPanels()
})

watch(browseConnectionKey, async () => {
  clearView()
  selectedCapId.value = null
  await loadMeta()
  await loadSamples()
})

function stopPoll() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
  pollInFlight.value = false
  pollFailStreak.value = 0
}

const pollInFlight = ref(false)
const pollFailStreak = ref(0)

function normalizeImportJobPayload(jobPayload) {
  const data = jobPayload?.data ?? jobPayload
  if (!data || typeof data !== 'object') return null
  if (data.job && typeof data.job === 'object') return data.job
  if (data.id != null || data.status != null) return data
  return null
}

async function pollImportJob(jobId) {
  if (jobId == null || jobId === '') {
    stopPoll()
    importing.value = false
    return
  }
  if (pollInFlight.value) return
  pollInFlight.value = true
  try {
    const res = await fetchFingerprintImportJobApi(jobId)
    const job = normalizeImportJobPayload(res)
    if (!job) {
      pollFailStreak.value += 1
      if (pollFailStreak.value >= 5) {
        stopPoll()
        importing.value = false
        ElMessage.error('导入进度接口连续返回异常格式，已停止轮询（导入可能仍在后台进行）')
      }
      return
    }
    pollFailStreak.value = 0
    importJob.value = job
    const status = job.status
    if (status === 'completed' || status === 'failed' || status === 'cancelled') {
      stopPoll()
      importing.value = false
      const dupTotal = Number(job.duplicate_report?.total || 0)
      if (dupTotal > 0) dupReportExpanded.value = true
      if (status === 'completed') {
        const wbFail = Number(job.writeback_failed || 0)
        const wbOk = Number(job.writeback_inserted || job.writeback_updated || 0)
        if (job.path_writeback_enabled && wbFail > 0) {
          ElMessage.warning(
            job.message || `导入完成，路径写回成功 ${wbOk} / 失败 ${wbFail}（见进度区）`,
          )
        } else if (dupTotal > 0) {
          ElMessage.warning(job.message || `导入完成，发现 ${dupTotal} 项重复`)
        } else {
          ElMessage.success(job.message || '导入完成')
        }
      } else if (status === 'failed') ElMessage.error(job.message || job.last_error || '导入失败')
      else ElMessage.warning(job.message || '已取消')
      await loadMeta()
      await loadSamples()
      if (selectedCapId.value) await loadView(selectedCapId.value)
    }
  } catch (err) {
    pollFailStreak.value += 1
    if (pollFailStreak.value >= 5) {
      stopPoll()
      importing.value = false
      ElMessage.error(err.message || '查询导入进度失败（导入可能仍在后台进行）')
    }
  } finally {
    pollInFlight.value = false
  }
}

function openImportDialog() {
  importFile.value = null
  importVersion.value = '1.0'
  importFailOnDuplicates.value = false
  resetWritebackForm()
  importDialogVisible.value = true
  ensureConnections()
}

watch(wbEnabled, (on) => {
  if (on) ensureConnections()
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
    pollTimer.value = setInterval(() => pollImportJob(job.id), 1200)
    await pollImportJob(job.id)
  } catch (err) {
    importing.value = false
    ElMessage.error(err.message || '启动导入失败')
  }
}

async function onCancelImport() {
  if (!importJob.value?.id) return
  try {
    await cancelFingerprintImportJobApi(importJob.value.id)
  } catch (err) {
    ElMessage.error(err.message || '取消失败')
  }
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

function openTypeDialog() {
  typeDialogVisible.value = true
}

async function submitNewType() {
  try {
    await createFingerprintLayerTypeApi({ ...typeForm })
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
  try {
    await updateFingerprintLayerTypeApi(row.id, { enabled: !row.enabled })
    await loadTypeRows()
    await loadMeta()
  } catch (err) {
    ElMessage.error(err.message || '更新失败')
  }
}

onMounted(async () => {
  await ensureConnections()
  await loadMeta()
  await loadSamples()
  const cap = route.query.cap || route.params.cap
  if (cap) {
    selectedCapId.value = String(cap)
    await loadView(String(cap))
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
        <h2>指纹特征浏览</h2>
        <p>业务表 T_CAP_FP_DATA → T_FEATURE_RECORD · 单图叠加细节点（预留双栏）</p>
      </div>
      <div class="import-actions">
        <el-select
          v-model="browseConnectionKey"
          filterable
          size="default"
          placeholder="业务库连接"
          style="width: 220px"
          :loading="browseLoading"
        >
          <el-option
            v-for="conn in wbConnections"
            :key="connectionKey(conn)"
            :label="conn.label || conn.alias"
            :value="connectionKey(conn)"
          />
        </el-select>
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
          · 路径写回 插入 {{ importJob.writeback_inserted || importJob.writeback_updated || 0 }}
          / 跳过 {{ importJob.writeback_skipped || 0 }}
          / 失败 {{ importJob.writeback_failed || 0 }}
        </template>
      </div>
      <div
        v-if="importJob.path_writeback_enabled && (importJob.writeback_errors || []).length"
        class="dup-report"
      >
        <div class="dup-report-head"><strong>写回错误</strong></div>
        <ul class="wb-errors">
          <li v-for="(err, i) in importJob.writeback_errors" :key="i">{{ err }}</li>
        </ul>
      </div>
      <div v-if="dupReport && dupReport.total > 0" class="dup-report">
        <div class="dup-report-head">
          <strong>重复检测</strong>
          <span class="muted">{{ dupReport.total }} 项</span>
          <el-button link type="primary" @click="dupReportExpanded = !dupReportExpanded">
            {{ dupReportExpanded ? '收起' : '展开' }}
          </el-button>
        </div>
        <div v-if="dupReportExpanded" class="dup-report-body">
          <div v-for="(w, idx) in dupWarningRows" :key="idx" class="dup-row">
            <el-tag size="small" type="warning">{{ dupTypeLabel(w.type) }}</el-tag>
            <span class="dup-paths">{{ (w.paths || w.names || []).join(' · ') }}</span>
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
          <strong>业务样本</strong>
          <span class="muted">共 {{ total }}</span>
        </div>
        <div class="filter-box">
          <el-input v-model="filters.keyword" clearable size="small" placeholder="cap_image_id" @keyup.enter="onSearch" />
          <el-select v-model="filters.dataset_code" clearable size="small" placeholder="dataset_code" style="width: 100%">
            <el-option v-for="c in meta.dataset_codes" :key="c" :label="c" :value="c" />
          </el-select>
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
          <el-empty
            v-else
            :description="browseConnectionKey ? '暂无业务样本（需先导入并启用路径写回）' : '请选择业务库连接'"
            :image-size="64"
          />
        </div>
        <div v-if="selectedCapId" class="selection-foot">
          <div class="sel-title">{{ selectedCapId }}</div>
          <div class="sel-meta">来自 T_CAP_FP_DATA</div>
        </div>
      </aside>

      <main class="compare-panel" v-loading="compareLoading">
        <template v-if="payload && primaryPanel">
          <div class="compare-toolbar">
            <div class="meta">
              {{ primaryPanel.cap_image_id }}
              <template v-if="primaryPanel.dataset_code"> · {{ primaryPanel.dataset_code }}</template>
              <template v-if="payload.mode"> · {{ payload.mode }}</template>
            </div>
            <div class="controls">
              <el-checkbox v-model="showLabels">编号</el-checkbox>
              <span class="label">缩放</span>
              <el-slider v-model="zoom" :min="0.5" :max="3" :step="0.1" style="width: 120px" />
            </div>
            <div
              v-if="(primaryPanel.layers || []).some((l) => l.error)"
              class="hint"
            >
              部分特征层加载失败，见下方勾选层旁提示
            </div>
          </div>

          <div class="compare-grid" :class="{ 'single-mode': panels.length < 2 }">
            <div
              v-for="(panel, idx) in panels"
              :key="panel.role || panel.cap_image_id || idx"
              class="pane"
            >
              <div class="pane-title">
                {{ panel.cap_image_id }}
                <span v-if="panel.role" class="muted"> · {{ panel.role }}</span>
              </div>
              <div class="canvas-wrap">
                <canvas :ref="(el) => setCanvasRef(idx, el)" />
              </div>
              <div class="pane-layers">
                <span class="label">特征层</span>
                <el-checkbox-group v-model="panelTypes">
                  <el-checkbox
                    v-for="opt in checkboxOptions"
                    :key="`${idx}-${opt.layer_key}`"
                    :label="opt.layer_key"
                    :value="opt.layer_key"
                  >
                    <span class="swatch" :style="{ background: opt.color }" />
                    {{ opt.label || opt.layer_key }}
                  </el-checkbox>
                </el-checkbox-group>
                <div
                  v-for="layer in (panel.layers || []).filter((l) => l.error)"
                  :key="`err-${layer.layer_type}`"
                  class="layer-error"
                >
                  {{ layer.layer_type }}: {{ layer.error }}
                </div>
              </div>
            </div>

            <!-- Reserved second pane when only one panel (future pair mode). -->
            <div v-if="panels.length < 2" class="pane pane-placeholder" aria-hidden="true">
              <div class="pane-title muted">配对栏（预留）</div>
              <div class="canvas-wrap placeholder-body">
                <el-empty description="关联表就绪后显示双栏对比" :image-size="48" />
              </div>
            </div>
          </div>
        </template>
        <el-empty v-else description="请在左侧树中选择一条业务样本" />
      </main>
    </div>

    <el-dialog v-model="importDialogVisible" title="导入 batmatch zip" width="640px">
      <p class="dialog-tip">
        导入仍写入本系统图库与配对表；开启<strong>路径写回</strong>后才会进入业务表，左侧树才能看到样本。
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

        <el-divider content-position="left">路径写回（浏览数据源）</el-divider>
        <p class="dialog-tip">
          固定写入 <code>ara_fp_analyst.T_CAP_FP_DATA</code> /
          <code>T_FEATURE_RECORD</code>；
          图像路径进 <code>fingerprint_image</code>，
          Bidiso→<code>feature_ara_data</code>，Neuiso→<code>feature_neuro_data</code>。
        </p>
        <el-form-item label="启用写回">
          <el-switch v-model="wbEnabled" />
        </el-form-item>
        <template v-if="wbEnabled">
          <el-form-item label="数据库连接" required>
            <el-select v-model="wbConnectionKey" filterable placeholder="选择能访问 ara_fp_analyst 的连接" style="width: 100%">
              <el-option
                v-for="conn in wbConnections"
                :key="connectionKey(conn)"
                :label="conn.label || conn.alias"
                :value="connectionKey(conn)"
              />
            </el-select>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitImport">开始导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="typeDialogVisible" title="特征类型配置" width="720px" @opened="loadTypeRows">
      <p class="dialog-tip">业务浏览当前映射：feature_ara_data→bidiso，feature_neuro_data→neuiso。</p>
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
  flex-wrap: wrap;
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
.compare-grid.single-mode .pane:first-child {
  /* keep two columns: primary + reserved */
}
.pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--el-border-color-lighter);
  background: #f7f7f7;
}
.pane:last-child { border-right: none; }
.pane-placeholder {
  background: #fafafa;
  opacity: 0.85;
}
.placeholder-body {
  display: flex;
  align-items: center;
  justify-content: center;
}
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
.pane-layers {
  flex-shrink: 0;
  padding: 8px 12px;
  background: #fff;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.layer-error {
  font-size: 12px;
  color: var(--el-color-danger);
  word-break: break-all;
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
:deep(.el-tree-node__content) {
  height: auto;
  min-height: 28px;
  padding: 4px 0;
  white-space: normal;
}
</style>
