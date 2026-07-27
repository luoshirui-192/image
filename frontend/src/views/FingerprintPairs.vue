<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchImageBlob,
  listBlobCatalogConnectionsApi,
} from '@/api/images'
import { useAuthStore } from '@/stores/auth'
import { usePageDataRefresh } from '@/utils/usePageDataRefresh'
import {
  createFingerprintLayerTypeApi,
  fetchFingerprintBizMetaApi,
  fetchFingerprintBizPairViewApi,
  fetchFingerprintBizPairViewByCapsApi,
  fetchFingerprintBizPairsApi,
  fetchFingerprintBizSampleViewApi,
  fetchFingerprintBizSamplesApi,
  fetchFingerprintLayerTypesApi,
  updateFingerprintLayerTypeApi,
} from '@/api/fingerprints'
import { executeSqlApi } from '@/api/sql'
import FingerprintImportDialog from '@/components/FingerprintImportDialog.vue'
import SqlEditor from '@/components/SqlEditor.vue'
import { useFingerprintImportStore } from '@/stores/fingerprintImport'
import {
  defaultBrowseSql,
  mapSqlResultToBrowseRows,
  pairSqlKey,
} from '@/utils/fingerprintSqlBrowse'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const fpImport = useFingerprintImportStore()

const loading = ref(false)
const compareLoading = ref(false)

const rows = ref([])
const total = ref(0)
const selectedMatchId = ref(null)
/** When pair row has no match id (SQL image_reg+image_match). */
const selectedPairCaps = ref(null) // { image_reg, image_match, data_set_code, sqlKey }
const selectedCapId = ref(null)
/** pair | single */
const browseMode = ref('pair')
/** filter | sql */
const listSourceMode = ref('filter')
const sqlTextPair = ref(defaultBrowseSql('pair'))
const sqlTextSingle = ref(defaultBrowseSql('single'))
const sqlRunning = ref(false)
const sqlHint = ref('')
const comparePanelRef = ref(null)
const treeRef = ref(null)

const importDialogVisible = ref(false)

const wbConnections = ref([])
const wbConnectionKey = ref('')

/** Browse connection (same catalog as writeback). */
const browseConnectionKey = ref('')
const browseLoading = ref(false)

const selectedBrowseConnection = computed(() =>
  wbConnections.value.find((c) => connectionKey(c) === browseConnectionKey.value) || null,
)

const activeImportJob = computed(() => fpImport.latestActive)

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

let suppressConnWatch = false

async function ensureConnections({ force = false } = {}) {
  if (wbConnections.value.length && !force) return
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
      // Avoid watch(browseConnectionKey) double-fetch while bootstrapping keys.
      suppressConnWatch = true
      try {
        if (!browseConnectionKey.value) browseConnectionKey.value = key
        if (!wbConnectionKey.value) wbConnectionKey.value = key
      } finally {
        suppressConnWatch = false
      }
    }
  } catch (err) {
    ElMessage.error(err.message || '加载数据库连接失败')
  } finally {
    browseLoading.value = false
  }
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
const pairMeta = computed(() => payload.value?.pair_meta || null)

const isPairMode = computed(() => browseMode.value === 'pair')
const isSqlListMode = computed(() => listSourceMode.value === 'sql')
const activeSqlText = computed({
  get: () => (isPairMode.value ? sqlTextPair.value : sqlTextSingle.value),
  set: (v) => {
    if (isPairMode.value) sqlTextPair.value = v
    else sqlTextSingle.value = v
  },
})

const sqlSimulateContext = computed(() => {
  const conn = selectedBrowseConnection.value
  if (!conn) return {}
  if (conn.connection_id != null) {
    return {
      connectionId: conn.connection_id,
      database: 'ara_fp_analyst',
      blobMode: 'path',
    }
  }
  return {
    dbAlias: conn.alias || 'default',
    database: conn.alias === 'default' || !conn.alias ? '' : 'ara_fp_analyst',
    blobMode: 'path',
  }
})

const treeData = computed(() => {
  const groups = new Map()
  for (const row of rows.value) {
    const key = isPairMode.value
      ? (row.data_set_code || 'unknown')
      : (row.dataset_code || 'unknown')
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(row)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([dataset, items]) => ({
      id: `ds:${dataset}`,
      label: `${dataset}（${items.length}）`,
      isGroup: true,
      children: items.map((row) => {
        if (isPairMode.value) {
          const nodeId =
            row.id != null
              ? `match:${row.id}`
              : `caps:${row._sqlKey || pairSqlKey(row.image_reg, row.image_match)}`
          return {
            id: nodeId,
            matchId: row.id,
            imageReg: row.image_reg,
            imageMatch: row.image_match,
            sqlKey: row._sqlKey,
            label:
              row.id != null
                ? `#${row.id} · ${row.image_reg || '?'} ↔ ${row.image_match || '?'}`
                : `${row.image_reg || '?'} ↔ ${row.image_match || '?'}`,
            isGroup: false,
            row,
          }
        }
        return {
          id: `cap:${row.cap_image_id}`,
          capImageId: row.cap_image_id,
          label: row.cap_image_id,
          isGroup: false,
          row,
        }
      }),
    }))
})

const currentNodeKey = computed(() => {
  if (isPairMode.value) {
    if (selectedMatchId.value != null) return `match:${selectedMatchId.value}`
    if (selectedPairCaps.value?.sqlKey) return `caps:${selectedPairCaps.value.sqlKey}`
    return undefined
  }
  return selectedCapId.value ? `cap:${selectedCapId.value}` : undefined
})

const hasSelection = computed(() =>
  isPairMode.value
    ? selectedMatchId.value != null || !!selectedPairCaps.value
    : !!selectedCapId.value,
)

const selectionTitle = computed(() => {
  if (isPairMode.value) {
    if (selectedMatchId.value != null) return `#${selectedMatchId.value}`
    if (selectedPairCaps.value) {
      return `${selectedPairCaps.value.image_reg} ↔ ${selectedPairCaps.value.image_match}`
    }
    return ''
  }
  return selectedCapId.value || ''
})

const selectionSource = computed(() => {
  if (isSqlListMode.value) {
    return isPairMode.value
      ? '来自 SQL（配对）'
      : '来自 SQL（单图）'
  }
  return isPairMode.value ? '来自 t_match_result_image' : '来自 T_CAP_FP_DATA'
})

const navPrevLabel = computed(() => (isPairMode.value ? '上一对' : '上一张'))
const navNextLabel = computed(() => (isPairMode.value ? '下一对' : '下一张'))
const emptyTreeHint = computed(() => {
  if (!browseConnectionKey.value) return '请选择业务库连接'
  if (isSqlListMode.value) {
    return isPairMode.value
      ? '执行 SQL 后在此显示配对结果'
      : '执行 SQL 后在此显示样本结果'
  }
  return isPairMode.value
    ? '暂无配对（需 t_match_result_image 有数据）'
    : '暂无样本（需 T_CAP_FP_DATA 有写回路径）'
})
const emptyMainHint = computed(() =>
  isPairMode.value ? '请在左侧树中选择一对指纹' : '请在左侧树中选择一张指纹',
)

const checkboxOptions = computed(() => {
  const available = new Set(payload.value?.available_layer_types || [])
  for (const panel of panels.value) {
    for (const t of panel.available_layer_types || []) available.add(t)
  }
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
  if (!params) return
  try {
    const res = await fetchFingerprintBizMetaApi(params)
    meta.dataset_codes = res.data.dataset_codes || []
    meta.layer_types = res.data.layer_types || []
  } catch (err) {
    ElMessage.error(err.message || '加载业务表元数据失败')
  }
}

let samplesLoadSeq = 0

async function loadSamples() {
  if (isSqlListMode.value) {
    // SQL mode keeps last executed result until user re-runs.
    return
  }
  const conn = selectedBrowseConnection.value
  const params = connectionQueryParams(conn)
  if (!params) return
  const seq = ++samplesLoadSeq
  loading.value = true
  sqlHint.value = ''
  try {
    const q = {
      ...params,
      page: 1,
      page_size: 500,
    }
    if (filters.keyword) q.keyword = filters.keyword
    if (filters.dataset_code) q.dataset_code = filters.dataset_code
    if (isPairMode.value) {
      const res = await fetchFingerprintBizPairsApi(q)
      if (seq !== samplesLoadSeq) return
      rows.value = res.data.items || []
      total.value = res.data.total || 0
      if (selectedMatchId.value != null && !rows.value.some((r) => r.id === selectedMatchId.value)) {
        selectedMatchId.value = null
        selectedPairCaps.value = null
        clearView()
      }
    } else {
      const res = await fetchFingerprintBizSamplesApi(q)
      if (seq !== samplesLoadSeq) return
      rows.value = res.data.items || []
      total.value = res.data.total || 0
      if (selectedCapId.value && !rows.value.some((r) => r.cap_image_id === selectedCapId.value)) {
        selectedCapId.value = null
        clearView()
      }
    }
  } catch (err) {
    if (seq !== samplesLoadSeq) return
    ElMessage.error(err.message || (isPairMode.value ? '加载配对列表失败' : '加载样本列表失败'))
  } finally {
    if (seq === samplesLoadSeq) loading.value = false
  }
}

async function runBrowseSql() {
  const conn = selectedBrowseConnection.value
  if (!conn) {
    ElMessage.warning('请先选择业务库连接')
    return
  }
  const sql = (activeSqlText.value || '').trim()
  if (!sql) {
    ElMessage.warning('请输入 SQL')
    return
  }
  sqlRunning.value = true
  loading.value = true
  try {
    const res = await executeSqlApi(sql, sqlSimulateContext.value)
    const columns = res.data?.columns || []
    const rawRows = res.data?.rows || []
    const mapped = mapSqlResultToBrowseRows(browseMode.value, columns, rawRows)
    if (mapped.error) {
      ElMessage.error(mapped.error)
      return
    }
    rows.value = mapped.items
    total.value = mapped.items.length
    selectedMatchId.value = null
    selectedPairCaps.value = null
    selectedCapId.value = null
    clearView()
    const trunc = res.data?.truncated ? '（已截断）' : ''
    const skip = mapped.skipped ? `，跳过无效行 ${mapped.skipped}` : ''
    sqlHint.value = `SQL 返回 ${mapped.items.length} 行${trunc}${skip}`
    if (!mapped.items.length) {
      ElMessage.warning('SQL 无有效结果行')
    } else {
      ElMessage.success(sqlHint.value)
    }
  } catch (err) {
    ElMessage.error(err.message || 'SQL 执行失败')
  } finally {
    sqlRunning.value = false
    loading.value = false
  }
}

function switchListSourceMode(mode) {
  if (mode !== 'filter' && mode !== 'sql') return
  if (listSourceMode.value === mode) return
  listSourceMode.value = mode
  selectedMatchId.value = null
  selectedPairCaps.value = null
  selectedCapId.value = null
  clearView()
  rows.value = []
  total.value = 0
  sqlHint.value = ''
  if (mode === 'filter') {
    void loadSamples()
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

const selectedSampleIndex = computed(() => {
  if (isPairMode.value) {
    if (selectedMatchId.value != null) {
      return rows.value.findIndex((r) => r.id === selectedMatchId.value)
    }
    if (selectedPairCaps.value?.sqlKey) {
      return rows.value.findIndex((r) => r._sqlKey === selectedPairCaps.value.sqlKey)
    }
    return -1
  }
  if (!selectedCapId.value) return -1
  return rows.value.findIndex((r) => r.cap_image_id === selectedCapId.value)
})

const canPrevSample = computed(() => selectedSampleIndex.value > 0)
const canNextSample = computed(
  () => selectedSampleIndex.value >= 0 && selectedSampleIndex.value < rows.value.length - 1,
)

function focusWithoutScroll(el) {
  if (!el || typeof el.focus !== 'function') return
  try {
    el.focus({ preventScroll: true })
  } catch {
    el.focus()
  }
}

function focusComparePanel() {
  nextTick(() => focusWithoutScroll(comparePanelRef.value))
}

function syncTreeCurrent() {
  nextTick(() => {
    treeRef.value?.setCurrentKey?.(currentNodeKey.value ?? null)
  })
}

function onTreeNodeClick(data) {
  if (data.isGroup) return
  if (isPairMode.value) {
    if (data.matchId != null) {
      selectPair(data.matchId, { focusPanel: true })
      return
    }
    if (data.imageReg && data.imageMatch) {
      selectPairByCaps(
        {
          image_reg: data.imageReg,
          image_match: data.imageMatch,
          data_set_code: data.row?.data_set_code || '',
          sqlKey: data.sqlKey || pairSqlKey(data.imageReg, data.imageMatch),
        },
        { focusPanel: true },
      )
    }
  } else {
    if (!data.capImageId) return
    selectSample(data.capImageId, { focusPanel: true })
  }
}

function selectPair(matchId, { focusPanel = false } = {}) {
  const id = Number(matchId)
  selectedMatchId.value = id
  selectedPairCaps.value = null
  selectedCapId.value = null
  syncTreeCurrent()
  router.replace({
    query: {
      ...route.query,
      mode: 'pair',
      match: String(id),
      cap: undefined,
      image_reg: undefined,
      image_match: undefined,
    },
  }).catch(() => {})
  loadView()
  if (focusPanel) focusComparePanel()
}

function selectPairByCaps(caps, { focusPanel = false } = {}) {
  const image_reg = String(caps.image_reg || '').trim()
  const image_match = String(caps.image_match || '').trim()
  if (!image_reg || !image_match) return
  selectedMatchId.value = null
  selectedPairCaps.value = {
    image_reg,
    image_match,
    data_set_code: caps.data_set_code || '',
    sqlKey: caps.sqlKey || pairSqlKey(image_reg, image_match),
  }
  selectedCapId.value = null
  syncTreeCurrent()
  router.replace({
    query: {
      ...route.query,
      mode: 'pair',
      match: undefined,
      cap: undefined,
      image_reg,
      image_match,
    },
  }).catch(() => {})
  loadView()
  if (focusPanel) focusComparePanel()
}

function selectSample(capImageId, { focusPanel = false } = {}) {
  const id = String(capImageId)
  selectedCapId.value = id
  selectedMatchId.value = null
  selectedPairCaps.value = null
  syncTreeCurrent()
  router.replace({
    query: {
      ...route.query,
      mode: 'single',
      cap: id,
      match: undefined,
      image_reg: undefined,
      image_match: undefined,
    },
  }).catch(() => {})
  loadView()
  if (focusPanel) focusComparePanel()
}

function goPrevSample() {
  if (compareLoading.value || !canPrevSample.value) return
  const prev = rows.value[selectedSampleIndex.value - 1]
  selectBrowseRow(prev, { focusPanel: true })
}

function goNextSample() {
  if (compareLoading.value || !canNextSample.value) return
  const next = rows.value[selectedSampleIndex.value + 1]
  selectBrowseRow(next, { focusPanel: true })
}

function selectBrowseRow(row, opts = {}) {
  if (!row) return
  if (isPairMode.value) {
    if (row.id != null) selectPair(row.id, opts)
    else if (row.image_reg && row.image_match) {
      selectPairByCaps(
        {
          image_reg: row.image_reg,
          image_match: row.image_match,
          data_set_code: row.data_set_code || '',
          sqlKey: row._sqlKey,
        },
        opts,
      )
    }
  } else if (row.cap_image_id) {
    selectSample(row.cap_image_id, opts)
  }
}

function onPreviewKeydown(event) {
  if (!rows.value.length || !hasSelection.value) return
  if (importDialogVisible.value || typeDialogVisible.value) return
  const tag = String(event.target?.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return
  if (event.target?.isContentEditable) return
  if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    event.preventDefault()
    goPrevSample()
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    event.preventDefault()
    goNextSample()
  }
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

async function loadView() {
  const conn = selectedBrowseConnection.value
  const params = connectionQueryParams(conn)
  if (!params) {
    ElMessage.warning('请先选择能访问 ara_fp_analyst 的数据库连接')
    return
  }
  if (isPairMode.value) {
    if (selectedMatchId.value == null && !selectedPairCaps.value) return
  } else if (!selectedCapId.value) {
    return
  }

  compareLoading.value = true
  layersReady.value = false
  try {
    let res
    if (isPairMode.value) {
      if (selectedMatchId.value != null) {
        res = await fetchFingerprintBizPairViewApi(selectedMatchId.value, {
          ...params,
          show_labels: '1',
        })
      } else {
        res = await fetchFingerprintBizPairViewByCapsApi({
          ...params,
          image_reg: selectedPairCaps.value.image_reg,
          image_match: selectedPairCaps.value.image_match,
          data_set_code: selectedPairCaps.value.data_set_code || undefined,
          show_labels: '1',
        })
      }
    } else {
      res = await fetchFingerprintBizSampleViewApi(selectedCapId.value, {
        ...params,
        show_labels: '1',
      })
    }
    payload.value = res.data
    const types = res.data.available_layer_types || []
    panelTypes.value = [...types]
    layersReady.value = true

    revokeUrls()
    const urls = []
    for (const panel of res.data.panels || []) {
      const path = panel.image?.path
      if (!path) {
        urls.push('')
        if (panel.image?.error || panel.error) {
          ElMessage.warning(`${panel.cap_image_id || panel.role}: ${panel.image?.error || panel.error}`)
        }
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
    ElMessage.error(err.message || (isPairMode.value ? '加载配对失败' : '加载样本失败'))
  } finally {
    compareLoading.value = false
  }
}

async function switchBrowseMode(mode) {
  if (mode !== 'pair' && mode !== 'single') return
  if (browseMode.value === mode) return
  browseMode.value = mode
  clearView()
  selectedMatchId.value = null
  selectedPairCaps.value = null
  selectedCapId.value = null
  router.replace({
    query: {
      ...route.query,
      mode,
      match: undefined,
      cap: undefined,
      image_reg: undefined,
      image_match: undefined,
    },
  }).catch(() => {})
  if (isSqlListMode.value) {
    rows.value = []
    total.value = 0
    sqlHint.value = ''
  } else {
    await loadSamples()
  }
}

function goEvalPage() {
  router.push({
    name: 'fingerprint-eval',
    query: {
      connection: browseConnectionKey.value || undefined,
      dataset_code: filters.dataset_code || undefined,
    },
  })
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
  if (suppressConnWatch) return
  clearView()
  selectedMatchId.value = null
  selectedPairCaps.value = null
  selectedCapId.value = null
  await loadMeta()
  if (!isSqlListMode.value) await loadSamples()
  else {
    rows.value = []
    total.value = 0
    sqlHint.value = ''
  }
})

function openImportDialog() {
  importDialogVisible.value = true
}

async function onImportStarted(job) {
  fpImport.trackJob(job)
}

function goTaskConsole() {
  void router.push({ path: '/blob-migrate' })
}

watch(typeDialogVisible, (open) => {
  if (open) void loadTypeRows()
})

let filterTimer = null
watch(
  () => [filters.keyword, filters.dataset_code],
  () => {
    if (filterTimer) clearTimeout(filterTimer)
    filterTimer = setTimeout(() => {
      void loadSamples()
    }, 350)
  },
)

// When an import finishes (polled on 任务台 / layout), refresh browse lists.
watch(
  () => fpImport.jobs.map((j) => `${j.id}:${j.status}`).join('|'),
  async (next, prev) => {
    if (!prev || next === prev) return
    const finished = fpImport.jobs.some(
      (j) => ['completed', 'failed', 'cancelled'].includes(j.status),
    )
    if (!finished) return
    await loadMeta()
    await loadSamples()
    if (hasSelection.value) await loadView()
  },
)

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

async function bootstrapFingerprintPage() {
  await ensureConnections()
  const modeQ = String(route.query.mode || '').toLowerCase()
  if (modeQ === 'single' || modeQ === 'pair') {
    browseMode.value = modeQ
  }
  await loadMeta()
  if (!isSqlListMode.value) {
    await loadSamples()
  }
  const matchQ = route.query.match || route.params.match
  const capQ = route.query.cap || route.params.cap
  const regQ = route.query.image_reg
  const matchCapQ = route.query.image_match
  if (browseMode.value === 'pair' && matchQ != null && matchQ !== '') {
    const id = Number(matchQ)
    if (!Number.isNaN(id)) {
      selectedMatchId.value = id
      syncTreeCurrent()
      await loadView()
      focusComparePanel()
    }
  } else if (browseMode.value === 'pair' && regQ && matchCapQ) {
    selectPairByCaps(
      {
        image_reg: String(regQ),
        image_match: String(matchCapQ),
        data_set_code: '',
      },
      { focusPanel: true },
    )
  } else if (browseMode.value === 'single' && capQ) {
    selectedCapId.value = String(capQ)
    syncTreeCurrent()
    await loadView()
    focusComparePanel()
  }
}

let fpBootstrapped = false
usePageDataRefresh(
  async () => {
    if (!fpBootstrapped) {
      await bootstrapFingerprintPage()
      fpBootstrapped = true
      return
    }
    // Reuse cached connections unless empty; force-refreshing every focus races loadSamples.
    await ensureConnections({ force: !wbConnections.value.length })
    if (!browseConnectionKey.value) return
    await loadMeta()
    if (!isSqlListMode.value) await loadSamples()
    if (selectedMatchId.value || selectedPairCaps.value || selectedCapId.value) {
      await loadView()
    }
  },
  {
    isEmpty: () => !rows.value.length && !wbConnections.value.length,
    alwaysRefreshOnVisible: true,
  },
)

onMounted(() => {
  window.addEventListener('keydown', onPreviewKeydown, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onPreviewKeydown, true)
  revokeUrls()
  if (filterTimer) clearTimeout(filterTimer)
})
</script>

<template>
  <div class="fp-page">
    <div class="fp-toolbar">
      <div class="fp-title">
        <h2>指纹特征浏览</h2>
        <p>单图读 T_CAP_FP_DATA；配对读 t_match_result_image</p>
      </div>
      <div class="import-actions">
        <el-radio-group :model-value="browseMode" size="default" @change="switchBrowseMode">
          <el-radio-button value="pair">配对</el-radio-button>
          <el-radio-button value="single">单图</el-radio-button>
        </el-radio-group>
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
        <el-button @click="goEvalPage">评测指标</el-button>
        <el-button v-if="auth.isAdmin" @click="openTypeDialog">特征类型</el-button>
        <el-button type="primary" @click="openImportDialog">导入 zip</el-button>
        <el-button plain @click="goTaskConsole">任务台</el-button>
      </div>
    </div>

    <el-alert
      v-if="activeImportJob"
      type="info"
      show-icon
      :closable="false"
      class="import-banner"
    >
      <template #title>
        导入进行中：{{ activeImportJob.zip_name || `#${activeImportJob.id}` }}
        · {{ activeImportJob.percent || 0 }}%
        ·
        <el-button link type="primary" @click="goTaskConsole">在任务台查看</el-button>
      </template>
    </el-alert>

    <div class="layout">
      <aside class="tree-panel" v-loading="loading">
        <div class="panel-head">
          <strong>{{ isPairMode ? '配对列表' : '样本列表' }}</strong>
          <span class="muted">共 {{ total }}</span>
        </div>
        <div class="filter-box">
          <el-radio-group
            :model-value="listSourceMode"
            size="small"
            class="list-source-toggle"
            @change="switchListSourceMode"
          >
            <el-radio-button value="filter">常规筛选</el-radio-button>
            <el-radio-button value="sql">SQL 筛选</el-radio-button>
          </el-radio-group>

          <template v-if="!isSqlListMode">
            <el-input
              v-model="filters.keyword"
              clearable
              size="small"
              :placeholder="isPairMode ? 'reg / match / id' : 'cap_image_id'"
              @keyup.enter="onSearch"
            />
            <el-select
              v-model="filters.dataset_code"
              clearable
              size="small"
              :placeholder="isPairMode ? 'data_set_code' : 'dataset_code'"
              style="width: 100%"
            >
              <el-option v-for="c in meta.dataset_codes" :key="c" :label="c" :value="c" />
            </el-select>
            <div class="filter-actions">
              <el-button type="primary" size="small" :loading="loading" @click="onSearch">筛选</el-button>
              <el-button size="small" @click="onReset">重置</el-button>
              <el-button size="small" :loading="loading" @click="onSearch">刷新</el-button>
            </div>
          </template>

          <template v-else>
            <p class="sql-tip">
              {{
                isPairMode
                  ? '结果需含 id，或同时含 image_reg + image_match'
                  : '结果需含 cap_image_id'
              }}
            </p>
            <SqlEditor v-model="activeSqlText" min-height="140px" @execute="runBrowseSql" />
            <div class="filter-actions">
              <el-button type="primary" size="small" :loading="sqlRunning" @click="runBrowseSql">
                执行并刷新列表
              </el-button>
            </div>
            <div v-if="sqlHint" class="sql-hint muted">{{ sqlHint }}</div>
          </template>
        </div>
        <div class="tree-wrap">
          <el-tree
            v-if="treeData.length"
            ref="treeRef"
            :data="treeData"
            node-key="id"
            default-expand-all
            highlight-current
            :current-node-key="currentNodeKey"
            :expand-on-click-node="false"
            @node-click="onTreeNodeClick"
          />
          <el-empty v-else :description="emptyTreeHint" :image-size="64" />
        </div>
        <div v-if="hasSelection" class="selection-foot">
          <div class="sel-title">{{ selectionTitle }}</div>
          <div class="sel-meta">
            {{ selectionSource }}
            <template v-if="selectedSampleIndex >= 0">
              · {{ selectedSampleIndex + 1 }}/{{ rows.length }}
            </template>
          </div>
        </div>
      </aside>

      <main
        ref="comparePanelRef"
        class="compare-panel"
        v-loading="compareLoading"
        tabindex="0"
      >
        <template v-if="payload && panels.length">
          <div class="compare-toolbar">
            <div class="meta">
              <template v-if="isPairMode && pairMeta">
                <template v-if="pairMeta.id != null">#{{ pairMeta.id }} · </template>
                {{ pairMeta.image_reg }} ↔ {{ pairMeta.image_match }}
                <template v-if="pairMeta.data_set_code"> · {{ pairMeta.data_set_code }}</template>
              </template>
              <template v-else-if="panels[0]">
                {{ panels[0].cap_image_id }}
                <template v-if="panels[0].dataset_code"> · {{ panels[0].dataset_code }}</template>
              </template>
              <template v-if="selectedSampleIndex >= 0">
                · {{ selectedSampleIndex + 1 }}/{{ rows.length }}
              </template>
            </div>
            <div class="controls">
              <el-button size="small" :disabled="!canPrevSample || compareLoading" @click="goPrevSample">
                {{ navPrevLabel }}
              </el-button>
              <el-button size="small" :disabled="!canNextSample || compareLoading" @click="goNextSample">
                {{ navNextLabel }}
              </el-button>
              <span class="hint">方向键切换</span>
              <el-checkbox v-model="showLabels">编号</el-checkbox>
              <span class="label">缩放</span>
              <el-slider v-model="zoom" :min="0.5" :max="3" :step="0.1" style="width: 120px" />
            </div>
            <div
              v-if="panels.some((p) => (p.layers || []).some((l) => l.error) || p.error)"
              class="hint"
            >
              部分侧图/特征加载失败，见各栏提示
            </div>
          </div>

          <div class="compare-grid" :class="{ 'single-mode': panels.length < 2 }">
            <div
              v-for="(panel, idx) in panels"
              :key="panel.role || panel.cap_image_id || idx"
              class="pane"
            >
              <div class="pane-title">
                <template v-if="panel.role === 'reg'">注册 · </template>
                <template v-else-if="panel.role === 'match'">比对 · </template>
                {{ panel.cap_image_id || '(缺失)' }}
              </div>
              <div class="canvas-wrap">
                <canvas v-if="panelUrls[idx]" :ref="(el) => setCanvasRef(idx, el)" />
                <el-empty
                  v-else
                  :description="panel.error || panel.image?.error || '无图像'"
                  :image-size="48"
                />
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
          </div>
        </template>
        <el-empty v-else :description="emptyMainHint" />
      </main>
    </div>

    <FingerprintImportDialog v-model="importDialogVisible" @started="onImportStarted" />

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
.import-banner {
  flex-shrink: 0;
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
  outline: none;
}
.compare-panel:focus,
.compare-panel:focus-visible {
  box-shadow: inset 0 0 0 1px var(--el-color-primary-light-5);
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
.list-source-toggle {
  width: 100%;
}
.list-source-toggle :deep(.el-radio-button) {
  flex: 1;
}
.list-source-toggle :deep(.el-radio-button__inner) {
  width: 100%;
}
.sql-tip,
.sql-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.4;
}
.sql-tip {
  color: var(--el-text-color-secondary);
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
.compare-grid.single-mode {
  grid-template-columns: 1fr;
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
