<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, VideoPlay, View } from '@element-plus/icons-vue'
import ImagePreview from '@/components/ImagePreview.vue'
import ImageLightbox from '@/components/ImageLightbox.vue'
import SqlEditor from '@/components/SqlEditor.vue'
import {
  createBlobMigrationJobApi,
  createBlobMigrationSourceApi,
  createBlobTableViewApi,
  deleteBlobTableViewApi,
  exportBlobTableViewToConnectionApi,
  fetchBlobTableViewRowsApi,
  getBlobCatalogObjectApi,
  listBlobCatalogConnectionsApi,
  listBlobCatalogDatabasesApi,
  listBlobCatalogObjectsApi,
  listBlobMigrationDatabasesApi,
  listBlobMigrationSourcesApi,
  listBlobMigrationMapStatsApi,
  listBlobTableViewsApi,
  listExternalDbConnectionsApi,
  updateBlobTableViewApi,
  getBlobMigrationSourceApi,
} from '@/api/images'
import {
  executeSqlApi,
  findPathColumn,
  formatCellValue,
  isPathCellValue,
  pathCellDisplay,
  rowsToRecords,
  sqlColumnMetaMap,
  validateSqlApi,
} from '@/api/sql'
import { highlightAndScrollTableRow } from '@/utils/tableScroll'
import { callWithRetry } from '@/utils/callWithRetry'
import { usePageDataRefresh } from '@/utils/usePageDataRefresh'
import { readBrowseUiState, writeBrowseUiState } from '@/utils/browseUiState'
import { useBackgroundExportStore } from '@/stores/backgroundExport'

const route = useRoute()
const router = useRouter()
const bgExport = useBackgroundExportStore()

const views = ref([])
const loadingViews = ref(false)
const activeViewId = ref(null)
const catalogTreeKey = ref(0)
const catalogTreeRef = ref(null)

const columns = ref([])
const tableRows = ref([])
const total = ref(-1)
const offset = ref(0)
const hasMore = ref(false)
const loadingRows = ref(false)
const loadingMore = ref(false)

const tableRef = ref(null)
const tableWrapRef = ref(null)
const browseHBarRef = ref(null)
const rowPreviewPanelRef = ref(null)
const tableHeight = ref(520)
let tableScrollEl = null
let resizeObserver = null
let sqlHScrollLock = false
let browseHScrollLock = false

const PAGE_SIZE = 80
const SCROLL_LOAD_DISTANCE = 120
const TABLE_SCROLLBAR_GUTTER = 14

const browseReady = ref(false)
let rowsLoadSeq = 0

const selectedRow = ref(null)

const activeView = computed(() => views.value.find((v) => v.id === activeViewId.value) || null)

const selectedRowPreviewItems = computed(() => {
  if (!selectedRow.value) return []
  return rowPreviewCells(selectedRow.value)
})

const selectedPreviewRowIndex = computed(() => {
  if (!selectedRow.value) return -1
  return tableRows.value.indexOf(selectedRow.value)
})

const browseLightboxOpen = ref(false)
const browseLightboxColumn = ref('')
const browseLightboxImageId = ref(null)
const browseLightboxPath = ref('')
const browseLightboxTitle = ref('')

function syncBrowseLightboxFromRow() {
  if (!browseLightboxOpen.value) return
  const items = selectedRowPreviewItems.value
  if (!items.length) {
    browseLightboxOpen.value = false
    return
  }
  const match =
    items.find((item) => item.column === browseLightboxColumn.value)
    || items[0]
  browseLightboxColumn.value = match.column
  browseLightboxImageId.value = match.cell?.image_info_id ?? null
  browseLightboxPath.value = match.cell?.path || ''
  browseLightboxTitle.value = match.title || match.cell?.path || match.column
}

function openBrowseLightbox(item) {
  if (!item?.cell?.image_info_id && !item?.cell?.path) return
  browseLightboxColumn.value = item.column
  browseLightboxImageId.value = item.cell?.image_info_id ?? null
  browseLightboxPath.value = item.cell?.path || ''
  browseLightboxTitle.value = item.title || item.cell?.path || item.column
  browseLightboxOpen.value = true
}

async function onBrowseLightboxPrev() {
  goPrevPreviewRow()
  await nextTick()
  syncBrowseLightboxFromRow()
}

async function onBrowseLightboxNext() {
  await goNextPreviewRow()
  await nextTick()
  syncBrowseLightboxFromRow()
}

watch(selectedRow, () => {
  syncBrowseLightboxFromRow()
})

function rowIdentityKey(row) {
  if (!row) return ''
  const pk = activeView.value?.source_pk_column
  if (pk && row[pk] != null) return String(row[pk])
  const imgId = getRowImageInfoId(row)
  if (imgId) return `img:${imgId}`
  return ''
}

function getRowKey(row) {
  const idx = tableRows.value.indexOf(row)
  const base = rowIdentityKey(row)
  if (idx >= 0) {
    return base ? `${base}#${idx}` : `row#${idx}`
  }
  return base || JSON.stringify(row)
}

const loadingCatalog = ref(false)
const selectedCatalogObject = ref(null)
const pendingRestorePk = ref('')

const rightTab = ref('browse')

const sqlText = ref('')
const sqlExecuting = ref(false)
const sqlValidating = ref(false)
const sqlResult = ref(null)
const sqlError = ref('')
const sqlTableData = ref([])
const sqlSelectedRow = ref(null)
const sqlTableRef = ref(null)
const sqlTableWrapRef = ref(null)
const sqlHBarRef = ref(null)
const sqlPreviewPanelRef = ref(null)

const migrationSources = ref([])
const mapStatsByTable = ref({})
const mapStatsByUid = ref({})
const selectionMigrationStats = ref(null)
const loadingSelectionMigrationStats = ref(false)

const migrateDialogVisible = ref(false)
const migrateSaving = ref(false)
const migrateForm = reactive({
  nameColumn: '',
  suffixColumn: '',
  tags: '',
})

const exportDialogVisible = ref(false)
const exportSaving = ref(false)
const exportError = ref('')
const exportTargets = ref([]) // { key, label, type: 'alias'|'conn', alias?, connectionId?, dbName? }
const exportDatabases = ref([])
const loadingExportTargets = ref(false)
const loadingExportDatabases = ref(false)
const exportForm = reactive({
  targetKey: '',
  database: '',
  tableName: '',
  ifExists: 'fail',
})

const selectedExportTarget = computed(() =>
  exportTargets.value.find((t) => t.key === exportForm.targetKey) || null,
)

const createViewDialogVisible = ref(false)
const createViewSaving = ref(false)
const createViewForm = reactive({
  name: '',
  sourcePkColumn: 'id',
  blobColumns: [],
  whereClause: '',
  alsoMigrate: false,
  startMigration: true,
  nameColumn: '',
  suffixColumn: '',
  tags: '',
})

const browseContext = computed(() => {
  if (activeView.value) {
    const view = activeView.value
    return {
      dbAlias: view.db_alias,
      database: view.database_name || '',
      connectionId: null,
      label: `${view.db_label || view.db_alias} · ${view.source_table}`,
    }
  }
  if (selectedCatalogObject.value) {
    const obj = selectedCatalogObject.value
    const conn = obj.connection || {}
    return {
      dbAlias: conn.alias,
      connectionId: conn.connection_id ?? null,
      database: obj.database || '',
      label: `${obj.database}.${obj.label}`,
    }
  }
  return {
    dbAlias: 'default',
    database: '',
    connectionId: null,
    label: '本系统库 (default)',
  }
})

const sqlSimulateContext = computed(() => {
  const base = { ...browseContext.value, blobMode: 'path' }
  if (activeView.value?.id) {
    return { ...base, viewId: activeView.value.id }
  }
  const saved = savedViewForSelection.value
  if (saved?.id) {
    return { ...base, viewId: saved.id }
  }
  const obj = selectedCatalogObject.value
  if (obj?.nodeType === 'object') {
    return {
      ...base,
      sourceTable: obj.label,
      sourcePkColumn: 'id',
      blobColumns: (obj.blobColumns || []).map((c) => c.column),
      sourceObjectType: obj.objectType === 'view' ? 'view' : 'table',
    }
  }
  return base
})

function rebuildSqlTableData() {
  const result = sqlResult.value
  sqlTableData.value = result ? rowsToRecords(result.columns, result.rows) : []
}

const sqlColumnMetaByName = computed(() => sqlColumnMetaMap(sqlResult.value?.column_meta))

const sqlPathColumn = computed(() => {
  if (!sqlResult.value) return null
  return findPathColumn(sqlResult.value.columns, sqlResult.value.rows)
})

const browseTableInnerStyle = computed(() => {
  if (!columns.value.length) return {}
  const width = columns.value.reduce(
    (sum, col) => sum + (col.is_path_substitute ? 200 : 100),
    0,
  )
  const px = `${Math.max(width, 100)}px`
  return { width: px, minWidth: px }
})

const sqlTableInnerStyle = computed(() => {
  const cols = sqlResult.value?.columns
  if (!cols?.length) return { minWidth: '100%' }
  const width = cols.reduce(
    (sum, col) => sum + sqlColumnWidth(col),
    0,
  )
  const px = `${Math.max(width, 100)}px`
  return { width: px, minWidth: px }
})

function sqlColumnWidth(colName) {
  if (sqlIsPathColumn(colName) || sqlPathColumn.value === colName) return 200
  return 120
}

function sqlIsPathColumn(colName) {
  return Boolean(sqlColumnMetaByName.value[colName]?.is_path_substitute)
}

function sqlPathCell(row, colName) {
  if (!row) return null
  const value = row[colName]
  if (isPathCellValue(value)) return value
  return null
}

function sqlFormatCell(row, colName) {
  if (!row) return '—'
  return pathCellDisplay(row[colName])
}

const sqlSelectedPreviewItems = computed(() => {
  const row = sqlSelectedRow.value
  if (!row || !sqlResult.value) return []
  return (sqlResult.value.columns || [])
    .filter((col) => sqlIsPathColumn(col) || sqlPathCell(row, col))
    .map((col) => {
      const cell = sqlPathCell(row, col)
      return cell?.image_info_id
        ? { column: col, cell, title: cell.path || cell.display || col }
        : null
    })
    .filter(Boolean)
})

const selectedSqlRowIndex = computed(() => {
  if (!sqlSelectedRow.value) return -1
  return sqlTableData.value.indexOf(sqlSelectedRow.value)
})

function catalogNodeLabel(data) {
  if (data.nodeType === 'connection') return data.label
  if (data.nodeType === 'database') {
    return data.isMigrationTarget ? `${data.label}（迁移库）` : data.label
  }
  if (data.nodeType === 'object') {
    const typeLabel = data.objectType === 'view' ? '数据库视图' : '表'
    return `${data.label} [${typeLabel}]`
  }
  return data.label
}

function viewCatalogKey(view) {
  return `${view.db_alias || ''}\0${view.database_name || ''}\0${view.source_table || ''}\0${view.source_object_type || 'table'}`
}

function catalogObjectKey(data) {
  const conn = data.connection || {}
  return `${conn.alias || ''}\0${data.database || ''}\0${data.label || ''}\0${data.objectType || 'table'}`
}

function findSavedViewForCatalogNode(data) {
  if (!data || data.nodeType !== 'object') return null
  const key = catalogObjectKey(data)
  const exact = views.value.find((view) => viewCatalogKey(view) === key)
  if (exact) return exact
  const conn = data.connection || {}
  return views.value.find((view) =>
    (view.db_alias || '') === (conn.alias || '')
    && (view.source_table || '') === (data.label || '')
    && (view.source_object_type || 'table') === (data.objectType || 'table')
    && !(view.database_name || '').trim()) || null
}

async function ensureSavedViewDatabaseMatchesCatalog(view, catalogDatabase) {
  const catalogDb = (catalogDatabase || '').trim()
  if (!view?.id || !catalogDb) return view
  const savedDb = (view.database_name || '').trim()
  if (savedDb === catalogDb) return view
  try {
    const res = await updateBlobTableViewApi(view.id, { database_name: catalogDb })
    const updated = res.data
    if (updated) {
      const idx = views.value.findIndex((item) => item.id === view.id)
      if (idx >= 0) {
        views.value[idx] = { ...views.value[idx], ...updated }
      }
    }
    const message = savedDb
      ? `已将配置的库名从「${savedDb}」同步为「${catalogDb}」`
      : `已自动补全配置的库名为「${catalogDb}」`
    ElMessage.info(message)
    return updated || view
  } catch (err) {
    ElMessage.warning(err.message || '同步库名失败，请删除配置后从目录重新创建')
    return view
  }
}

const savedViewForSelection = computed(() => {
  if (!selectedCatalogObject.value) return null
  return findSavedViewForCatalogNode(selectedCatalogObject.value)
})

const catalogDatabaseMismatch = computed(() => {
  if (!activeView.value || !selectedCatalogObject.value) return ''
  const catalogDb = (selectedCatalogObject.value.database || '').trim()
  const viewDb = (activeView.value.database_name || '').trim()
  if (!catalogDb || !viewDb || catalogDb === viewDb) return ''
  return `左侧目录为「${catalogDb}」，当前配置库名为「${viewDb || '（空）'}」`
})

function viewMigrationKey(view) {
  if (!view) return ''
  return `${view.db_alias || ''}\0${view.database_name || ''}\0${view.source_table || ''}\0${view.source_object_type || 'table'}`
}

function migrationSourceCandidates(view, catalogData = null) {
  if (!view && !catalogData) return []
  const viewUid = (view?.source_uid || '').trim()
  if (viewUid) {
    const byUid = migrationSources.value.filter((source) => (source.source_uid || '').trim() === viewUid)
    if (byUid.length) return byUid
  }

  const dbAlias = (view?.db_alias || catalogData?.connection?.alias || '').trim()
  const table = (view?.source_table || catalogData?.label || '').trim()
  const objType = (view?.source_object_type || catalogData?.objectType || 'table').trim() || 'table'
  if (!dbAlias || !table) return []

  return migrationSources.value.filter((source) => {
    if ((source.db_alias || '').trim() !== dbAlias) return false
    if ((source.source_table || '').trim() !== table) return false
    return (source.source_object_type || 'table').trim() === objType
  })
}

function sourceDatabaseName(source) {
  return (source?.database_name || '').trim()
}

function isMigrationMatchAmbiguous(view, catalogData = null) {
  const viewUid = (view?.source_uid || '').trim()
  if (viewUid) {
    const byUid = migrationSources.value.filter((source) => (source.source_uid || '').trim() === viewUid)
    return byUid.length > 1
  }

  const candidates = migrationSourceCandidates(view, catalogData)
  const catalogDb = (view?.database_name || catalogData?.database || '').trim()
  if (!candidates.length) return false
  if (!catalogDb) return candidates.length > 1

  const exact = candidates.filter((source) => sourceDatabaseName(source) === catalogDb)
  if (exact.length > 1) return true

  const emptyDb = candidates.filter((source) => !sourceDatabaseName(source))
  if (emptyDb.length > 1) return true
  if (emptyDb.length && candidates.length > 1) return true
  return false
}

function findMigrationSourceForView(view, catalogData = null) {
  const candidates = migrationSourceCandidates(view, catalogData)
  const catalogDb = (view?.database_name || catalogData?.database || '').trim()
  if (!candidates.length) return null
  if (isMigrationMatchAmbiguous(view, catalogData)) return null

  if (catalogDb) {
    const exact = candidates.find((source) => sourceDatabaseName(source) === catalogDb)
    if (exact) return exact

    const emptyDb = candidates.filter((source) => !sourceDatabaseName(source))
    const explicitOther = candidates.some(
      (source) => sourceDatabaseName(source) && sourceDatabaseName(source) !== catalogDb,
    )
    if (explicitOther) return null

    if (emptyDb.length === 1 && candidates.length === 1) {
      const resolved = sourceDatabaseName(emptyDb[0])
      if (!resolved || resolved === catalogDb) return emptyDb[0]
      return null
    }
    return null
  }

  return candidates.length === 1 ? candidates[0] : null
}

function blobColumnsFromView(view) {
  if (!view) return []
  const raw = view.blob_columns
  if (Array.isArray(raw) && raw.length) return raw
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length) return parsed
    } catch {
      // ignore invalid JSON
    }
  }
  return view.blob_column ? [view.blob_column] : []
}

function objectHasMigratableBlob(catalogData, view) {
  if (blobColumnsFromView(view).length) return true
  return !!(catalogData?.blobColumns?.length)
}

function mapLookupTables(view, catalogData) {
  const tables = []
  const seen = new Set()
  const add = (name) => {
    const value = (name || '').trim()
    if (!value || seen.has(value)) return
    seen.add(value)
    tables.push(value)
  }
  add(view?.path_lookup_table)
  add(view?.source_table || catalogData?.label)
  return tables
}

function countMapMigratedEntries(source) {
  if (!source) return 0
  const uid = (source.source_uid || '').trim()
  if (uid) {
    return Number(mapStatsByUid.value[uid] || 0)
  }
  let total = 0
  for (const table of mapLookupTables(source, null)) {
    total += Number(mapStatsByTable.value[table] || 0)
  }
  return total
}

function resolveMigrationHint({ stats, view, catalogData, loading = false }) {
  if (!objectHasMigratableBlob(catalogData, view)) return null
  if (loading) return { text: '检测迁移状态…', type: 'info' }

  if (isMigrationMatchAmbiguous(view, catalogData)) {
    return { text: '迁移状态不明', type: 'warning' }
  }

  const source = findMigrationSourceForView(view, catalogData)
  const resolvedStats = stats?.noSource
    ? null
    : (stats ?? source?.stats ?? null)

  if (source?.id && resolvedStats && !resolvedStats.error) {
    const pending = Number(resolvedStats.pending ?? 0)
    if (pending > 0) return { text: `待迁移 ${pending}`, type: 'warning' }

    const migrated = Number(resolvedStats.migrated ?? 0)
    const total = Number(resolvedStats.total_with_blob ?? 0)
    if (total > 0 && migrated >= total) return { text: '已迁完', type: 'success' }
    if (migrated > 0) return { text: `已迁移 ${migrated}/${total}`, type: 'success' }
    return { text: '无可迁移', type: 'info' }
  }

  if (source) {
    const mapped = countMapMigratedEntries(source)
    if (mapped > 0) return { text: `已迁移 ${mapped}`, type: 'success' }
  }

  return null
}

function catalogMigrationTag(data) {
  if (!data || data.nodeType !== 'object') return null
  const view = findSavedViewForCatalogNode(data)
  const source = findMigrationSourceForView(view, data)
  return resolveMigrationHint({
    stats: source?.stats,
    view,
    catalogData: data,
    loading: false,
  })
}

const selectionMigrationTag = computed(() => {
  const view = savedViewForSelection.value
  const catalogData = selectedCatalogObject.value
  const source = findMigrationSourceForView(view, catalogData)
  const stats = selectionMigrationStats.value?.noSource
    ? null
    : (selectionMigrationStats.value ?? source?.stats ?? null)
  return resolveMigrationHint({
    stats,
    view,
    catalogData,
    loading: loadingSelectionMigrationStats.value,
  })
})

const selectionMigrationHint = computed(() => selectionMigrationTag.value?.text || '')

const showMigrateForSelection = computed(() => {
  if (!savedViewForSelection.value) return false
  if (loadingSelectionMigrationStats.value) return false
  const stats = selectionMigrationStats.value
  if (!stats) return false
  if (stats.noSource) return objectHasMigratableBlob(selectedCatalogObject.value, savedViewForSelection.value)
  if (stats.error) return false
  return Number(stats.pending ?? 0) > 0
})

async function loadCatalogTree(root, resolve) {
  loadingCatalog.value = true
  try {
    if (root.level === 0) {
      const res = await callWithRetry(() => listBlobCatalogConnectionsApi())
      const items = res.data || []
      resolve(
        items.map((conn) => ({
          id: `conn:${conn.alias}`,
          label: conn.label || conn.alias,
          nodeType: 'connection',
          connection: conn,
          leaf: false,
        })),
      )
      return
    }

    const data = root.data
    if (data.nodeType === 'connection') {
      const conn = data.connection
      const params = conn.connection_id != null
        ? { connectionId: conn.connection_id }
        : { dbAlias: conn.alias }
      const res = await callWithRetry(() => listBlobCatalogDatabasesApi(params))
      resolve(
        (res.data?.databases || []).map((db) => ({
          id: `db:${conn.alias}:${db.name}`,
          label: db.name,
          nodeType: 'database',
          connection: conn,
          database: db.name,
          isMigrationTarget: db.is_migration_target,
          leaf: false,
        })),
      )
      return
    }

    if (data.nodeType === 'database') {
      const conn = data.connection
      const params = {
        database: data.database,
        ...(conn.connection_id != null ? { connectionId: conn.connection_id } : { dbAlias: conn.alias }),
      }
      const res = await callWithRetry(() => listBlobCatalogObjectsApi(params))
      resolve(
        (res.data?.objects || []).map((obj) => ({
          id: `obj:${conn.alias}:${data.database}:${obj.name}`,
          label: obj.name,
          nodeType: 'object',
          connection: conn,
          database: data.database,
          objectType: obj.object_type,
          blobColumns: obj.blob_columns || [],
          leaf: true,
        })),
      )
      return
    }

    resolve([])
  } catch (err) {
    ElMessage.error(err.message || '加载目录失败')
    resolve([])
  } finally {
    loadingCatalog.value = false
  }
}

function onCatalogNodeClick(data) {
  if (data.nodeType === 'database') {
    selectedCatalogObject.value = null
    activeViewId.value = null
    persistBrowseUiState()
    return
  }
  if (data.nodeType !== 'object') return
  void onCatalogObjectSelected(data)
}

async function onCatalogObjectSelected(data) {
  selectedCatalogObject.value = data
  sqlText.value = `SELECT * FROM \`${data.label}\` LIMIT 80`
  const saved = findSavedViewForCatalogNode(data)
  if (saved) {
    const synced = await ensureSavedViewDatabaseMatchesCatalog(saved, data.database)
    activeViewId.value = synced?.id ?? saved.id
    rightTab.value = 'browse'
  } else {
    activeViewId.value = null
  }
  persistBrowseUiState()
}

async function loadMigrationSources({ includeStats = false } = {}) {
  try {
    const res = await callWithRetry(() => listBlobMigrationSourcesApi({ includeStats }))
    migrationSources.value = res.data || []
  } catch {
    migrationSources.value = []
  }
}

async function loadMapStats() {
  try {
    const res = await callWithRetry(() => listBlobMigrationMapStatsApi())
    mapStatsByTable.value = res.data?.by_source_table || {}
    mapStatsByUid.value = res.data?.by_source_uid || {}
  } catch {
    mapStatsByTable.value = {}
    mapStatsByUid.value = {}
  }
}

async function refreshSelectionMigrationStats() {
  const view = savedViewForSelection.value
  const catalogData = selectedCatalogObject.value
  if (!view) {
    selectionMigrationStats.value = null
    return
  }
  const source = findMigrationSourceForView(view, catalogData)
  if (!source?.id) {
    selectionMigrationStats.value = { noSource: true }
    return
  }
  loadingSelectionMigrationStats.value = true
  try {
    const res = await getBlobMigrationSourceApi(source.id, { includeStats: true })
    selectionMigrationStats.value = res.data?.stats || { error: true }
  } catch {
    selectionMigrationStats.value = { error: true }
  } finally {
    loadingSelectionMigrationStats.value = false
  }
}

function buildMigrationSourcePayload(view, form) {
  return {
    name: `${view.name || view.source_table} 迁移`,
    source_uid: (view.source_uid || '').trim() || undefined,
    db_alias: view.db_alias,
    database_name: view.database_name || '',
    source_table: view.source_table,
    source_object_type: view.source_object_type || 'table',
    source_pk_column: view.source_pk_column || 'id',
    blob_columns: blobColumnsFromView(view),
    path_lookup_table: view.path_lookup_table || '',
    blob_column_path_mappings: view.blob_column_path_mappings || [],
    where_clause: view.where_clause || '',
    name_column: form.nameColumn.trim(),
    suffix_column: form.suffixColumn.trim(),
    tags: form.tags.trim(),
  }
}

async function startMigrationJob(sourceId) {
  const jobRes = await createBlobMigrationJobApi({
    sourceId,
    batchSize: 100,
    dryRun: false,
    skipExisting: true,
    runAll: true,
    warmThumbsAfter: true,
  })
  return jobRes.data
}

async function ensureMigrationSourceForView(view, form, catalogData = null) {
  const existing = findMigrationSourceForView(view, catalogData ?? selectedCatalogObject.value)
  if (existing?.id) return existing.id
  const sourceRes = await createBlobMigrationSourceApi(buildMigrationSourcePayload(view, form), {
    includeStats: false,
  })
  const sourceId = sourceRes.data?.id
  if (sourceId) {
    await loadMigrationSources()
  }
  return sourceId
}

async function openMigrateDialog() {
  const view = savedViewForSelection.value
  if (!view) return
  migrateForm.nameColumn = ''
  migrateForm.suffixColumn = ''
  migrateForm.tags = ''
  migrateDialogVisible.value = true
}

async function submitSavedViewMigration() {
  const view = savedViewForSelection.value
  if (!view) return
  migrateSaving.value = true
  try {
    const sourceId = await ensureMigrationSourceForView(view, migrateForm)
    if (!sourceId) {
      ElMessage.error('创建迁移配置失败')
      return
    }
    const job = await startMigrationJob(sourceId)
    const jobId = job?.id
    const estimate = Number(job?.total_estimate ?? 0)
    let message = jobId ? `已启动迁移任务 #${jobId}` : '已启动迁移任务'
    if (estimate <= 0 && job?.status === 'completed') {
      message = '当前无待迁移项'
    }
    ElMessage.success(message)
    migrateDialogVisible.value = false
    migrateSaving.value = false
    void Promise.all([loadMigrationSources(), loadMapStats()]).then(() => refreshSelectionMigrationStats())
  } catch (err) {
    ElMessage.error(err.message || '启动迁移失败')
  } finally {
    migrateSaving.value = false
  }
}

async function loadExportTargets() {
  loadingExportTargets.value = true
  try {
    const [dbRes, connRes] = await Promise.all([
      callWithRetry(() => listBlobMigrationDatabasesApi()),
      callWithRetry(() => listExternalDbConnectionsApi()),
    ])
    const dbs = dbRes.data || []
    const conns = (connRes.data || []).filter((item) => item.enabled !== 0)
    const items = []
    for (const db of dbs) {
      items.push({
        key: `alias:${db.alias}`,
        label: db.label
          ? `${db.label}（${db.alias}）`
          : `${db.alias}（${db.name || db.alias}@${db.host || 'local'}）`,
        type: 'alias',
        alias: db.alias,
        dbName: db.name || '',
      })
    }
    for (const conn of conns) {
      // Skip if already represented as migration alias
      if (items.some((i) => i.type === 'alias' && i.alias === conn.alias)) continue
      items.push({
        key: `conn:${conn.id}`,
        label: `${conn.name}（${conn.host}/${conn.db_name}）`,
        type: 'conn',
        connectionId: conn.id,
        dbName: conn.db_name || '',
      })
    }
    if (items.length || !exportTargets.value.length) {
      exportTargets.value = items
    }
  } catch {
    if (!exportTargets.value.length) exportTargets.value = []
  } finally {
    loadingExportTargets.value = false
  }
}

async function loadExportDatabasesForTarget(target) {
  const prevDb = exportForm.database
  if (!target) {
    exportDatabases.value = []
    exportForm.database = ''
    return
  }
  loadingExportDatabases.value = true
  try {
    const params = target.type === 'conn'
      ? { connectionId: target.connectionId }
      : { dbAlias: target.alias }
    const res = await callWithRetry(() => listBlobCatalogDatabasesApi(params))
    const list = res.data?.databases || res.data || []
    const names = Array.isArray(list)
      ? list.map((item) => (typeof item === 'string' ? item : item.name || item.database || '')).filter(Boolean)
      : []
    exportDatabases.value = names
    if (prevDb && names.includes(prevDb)) {
      exportForm.database = prevDb
    } else if (target.dbName && names.includes(target.dbName)) {
      exportForm.database = target.dbName
    } else if (names.length === 1) {
      exportForm.database = names[0]
    } else {
      exportForm.database = ''
    }
  } catch (err) {
    if (!exportDatabases.value.length) {
      ElMessage.error(err.message || '加载目标库列表失败')
    }
  } finally {
    loadingExportDatabases.value = false
  }
}

async function openExportDialog() {
  const view = savedViewForSelection.value
  if (!view) return
  exportError.value = ''
  exportForm.targetKey = ''
  exportForm.database = ''
  exportForm.tableName = view.source_table || ''
  exportForm.ifExists = 'fail'
  exportDatabases.value = []
  await loadExportTargets()
  exportDialogVisible.value = true
}

async function onExportTargetChange(targetKey) {
  const target = exportTargets.value.find((t) => t.key === targetKey) || null
  await loadExportDatabasesForTarget(target)
}

async function openTargetBrowseView(result) {
  const viewId = result?.target_view_id
  if (!viewId) return
  catalogTreeKey.value += 1
  await loadViews()
  activeViewId.value = viewId
  rightTab.value = 'browse'
  await router.replace({ query: { ...route.query, viewId: String(viewId) } }).catch(() => {})
  browseReady.value = true
  await loadRows({ append: false })
}

async function submitExportToConnection() {
  const view = savedViewForSelection.value
  if (!view?.id) return
  const target = selectedExportTarget.value
  if (!target) {
    ElMessage.warning('请选择目标连接 / 数据库别名')
    return
  }
  if (!exportForm.database) {
    ElMessage.warning('请选择目标数据库')
    return
  }
  if (!exportForm.tableName.trim()) {
    ElMessage.warning('请填写目标表名')
    return
  }
  exportSaving.value = true
  exportError.value = ''
  try {
    const payload = {
      target_database: exportForm.database,
      target_table: exportForm.tableName.trim(),
      if_exists: exportForm.ifExists,
    }
    if (target.type === 'conn') {
      payload.target_connection_id = target.connectionId
    } else {
      payload.target_db_alias = target.alias
    }
    const res = await exportBlobTableViewToConnectionApi(view.id, payload)
    const job = res?.data?.job
    if (!job?.id) {
      throw new Error('未拿到导出任务')
    }
    // Hand off to global dock — close dialog so user can leave and do other work.
    bgExport.trackJob(job)
    exportDialogVisible.value = false
    // If already finished (sync test mode), refresh catalog once.
    if (job.status === 'completed') {
      await loadViews()
      catalogTreeKey.value += 1
    }
  } catch (err) {
    exportError.value = err.message || '启动导出失败'
    ElMessage.error(exportError.value)
  } finally {
    exportSaving.value = false
  }
}

function closeExportDialog() {
  exportDialogVisible.value = false
  exportError.value = ''
  exportSaving.value = false
}

async function openCreateViewDialog() {
  if (!selectedCatalogObject.value) return
  const obj = selectedCatalogObject.value
  const conn = obj.connection || {}
  createViewForm.name = obj.label
  createViewForm.blobColumns = (obj.blobColumns || []).map((item) => item.column)
  createViewForm.whereClause = ''
  createViewForm.sourcePkColumn = 'id'
  createViewForm.alsoMigrate = false
  createViewForm.startMigration = true
  createViewForm.nameColumn = ''
  createViewForm.suffixColumn = ''
  createViewForm.tags = ''
  try {
    const res = await getBlobCatalogObjectApi(obj.label, {
      connectionId: conn.connection_id,
      dbAlias: conn.alias,
      database: obj.database,
    })
    const detail = res.data || {}
    const pkCol = detail.columns?.find((col) => col.column_key === 'PRI')?.name
      || detail.columns?.find((col) => col.name === 'id')?.name
    if (pkCol) createViewForm.sourcePkColumn = pkCol
    if (!createViewForm.blobColumns.length && detail.blob_columns?.length) {
      createViewForm.blobColumns = detail.blob_columns.map((item) => item.column)
    }
  } catch {
    // keep defaults from tree node
  }
  createViewDialogVisible.value = true
}

async function submitCreateView() {
  if (!selectedCatalogObject.value) return
  if (!createViewForm.blobColumns.length) {
    ElMessage.warning('请至少选择一个 BLOB 列')
    return
  }
  const obj = selectedCatalogObject.value
  const conn = obj.connection || {}
  const sharedPayload = {
    name: createViewForm.name.trim() || obj.label,
    db_alias: conn.alias,
    database_name: obj.database,
    source_table: obj.label,
    source_object_type: obj.objectType || 'table',
    source_pk_column: createViewForm.sourcePkColumn.trim() || 'id',
    blob_columns: [...createViewForm.blobColumns],
    where_clause: createViewForm.whereClause.trim(),
  }
  createViewSaving.value = true
  try {
    const res = await createBlobTableViewApi(sharedPayload)
    let message =
      res.data?.blob_column_path_mappings?.length
        ? `配置已创建，已自动解析 ${res.data.blob_column_path_mappings.length} 个 BLOB 列路径映射`
        : '配置已创建'

    if (createViewForm.alsoMigrate) {
      const sourceId = await ensureMigrationSourceForView(res.data, createViewForm)
      message += sourceId
        ? `；迁移配置已保存（#${sourceId}）`
        : '；迁移配置已保存'

      if (createViewForm.startMigration && sourceId) {
        const job = await startMigrationJob(sourceId)
        const jobId = job?.id
        const estimate = Number(job?.total_estimate ?? 0)
        if (estimate <= 0 && job?.status === 'completed') {
          message += '；当前无待迁移项'
        } else {
          message += jobId ? `；已启动迁移任务 #${jobId}` : '；已启动迁移任务'
        }
      }
    }

    ElMessage.success(message)
    createViewDialogVisible.value = false
    await loadViews()
    if (res.data?.id) {
      activeViewId.value = res.data.id
      rightTab.value = 'browse'
    }
  } catch (err) {
    ElMessage.error(err.message || '创建失败')
  } finally {
    createViewSaving.value = false
  }
}

async function handleSqlValidate() {
  const sql = sqlText.value.trim()
  if (!sql) {
    ElMessage.warning('请输入 SQL')
    return
  }
  sqlValidating.value = true
  sqlError.value = ''
  try {
    await validateSqlApi(sql, sqlSimulateContext.value)
    ElMessage.success('SQL 校验通过')
  } catch (err) {
    sqlError.value = err.message || '校验失败'
  } finally {
    sqlValidating.value = false
  }
}

async function handleSqlExecute() {
  const sql = sqlText.value.trim()
  if (!sql) {
    ElMessage.warning('请输入 SQL')
    return
  }
  sqlExecuting.value = true
  sqlError.value = ''
  try {
    const res = await executeSqlApi(sql, sqlSimulateContext.value)
    sqlResult.value = res.data
    rebuildSqlTableData()
    await nextTick()
    selectSqlPreviewRow(sqlTableData.value[0] ?? null, { focusBrowse: true })
    setupSqlTableViewport()
    await nextTick()
    layoutTableRefs()
  } catch (err) {
    sqlResult.value = null
    sqlTableData.value = []
    sqlSelectedRow.value = null
    sqlError.value = err.message || '执行失败'
  } finally {
    sqlExecuting.value = false
  }
}

function formatCell(row, colName) {
  if (!row) return '—'
  const value = row[colName]
  if (value && typeof value === 'object' && 'display' in value) {
    return value.display
  }
  if (value == null) return '—'
  return String(value)
}

function pathCell(row, colName) {
  if (!row) return null
  const value = row[colName]
  if (value && typeof value === 'object') return value
  return null
}

function autoSelectFirstRow() {
  const row = tableRows.value[0] ?? null
  selectPreviewRow(row)
}

function selectPreviewRow(row, { focusPanel = false } = {}) {
  selectedRow.value = row
  syncTableCurrentRow(row)
  persistBrowseUiState()
  if (focusPanel) {
    nextTick(() => rowPreviewPanelRef.value?.focus())
  }
}

function goPrevPreviewRow() {
  const rows = tableRows.value
  if (rows.length <= 1) return
  const idx = selectedPreviewRowIndex.value
  if (idx <= 0) return
  selectPreviewRow(rows[idx - 1])
}

async function goNextPreviewRow() {
  const rows = tableRows.value
  if (!rows.length) return
  const idx = selectedPreviewRowIndex.value
  if (idx < 0) {
    selectPreviewRow(rows[0])
    return
  }
  if (idx < rows.length - 1) {
    selectPreviewRow(rows[idx + 1])
    return
  }
  if (!hasMore.value || loadingMore.value) return
  const prevLen = rows.length
  await loadRows({ append: true })
  const nextRows = tableRows.value
  if (nextRows.length > prevLen) {
    selectPreviewRow(nextRows[idx + 1])
  }
}

function onPreviewKeydown(event) {
  if (!tableRows.value.length) return
  if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    event.preventDefault()
    goPrevPreviewRow()
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    event.preventDefault()
    void goNextPreviewRow()
  }
}

function focusSqlBrowse() {
  nextTick(() => sqlTableWrapRef.value?.focus())
}

function selectSqlPreviewRow(row, { focusPanel = false, focusBrowse = false } = {}) {
  sqlSelectedRow.value = row
  syncSqlTableCurrentRow(row)
  if (focusPanel) {
    nextTick(() => sqlPreviewPanelRef.value?.focus())
  }
  if (focusBrowse || focusPanel) {
    focusSqlBrowse()
  }
}

function goPrevSqlPreviewRow() {
  const rows = sqlTableData.value
  if (rows.length <= 1) return
  const idx = selectedSqlRowIndex.value
  if (idx <= 0) return
  selectSqlPreviewRow(rows[idx - 1])
}

function goNextSqlPreviewRow() {
  const rows = sqlTableData.value
  if (!rows.length) return
  const idx = selectedSqlRowIndex.value
  if (idx < 0) {
    selectSqlPreviewRow(rows[0])
    return
  }
  if (idx < rows.length - 1) {
    selectSqlPreviewRow(rows[idx + 1])
  }
}

function onSqlPreviewKeydown(event) {
  if (!sqlTableData.value.length) return
  if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    event.preventDefault()
    goPrevSqlPreviewRow()
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    event.preventDefault()
    goNextSqlPreviewRow()
  }
}

function getSqlRowKey(row) {
  const idx = sqlTableData.value.indexOf(row)
  return idx >= 0 ? `sql-${idx}` : `sql-${String(row?.id ?? row?.ID ?? '')}`
}

function onSqlTableRowClick(row, _column, event) {
  if (event?.target?.closest?.('button, a, .el-button')) return
  selectSqlPreviewRow(row, { focusBrowse: true })
}

function onTableRowClick(row, _column, event) {
  if (event?.target?.closest?.('button, a, .el-button')) return
  selectPreviewRow(row, { focusPanel: true })
  nextTick(() => tableWrapRef.value?.focus())
}

function rowPreviewCells(row) {
  return blobColumnNames()
    .map((col) => {
      const cell = pathCell(row, col)
      const imageId = cell?.image_info_id
      if (imageId == null || imageId === '' || cell?.status !== 'migrated') return null
      return {
        column: col,
        cell: {
          ...cell,
          image_info_id: Number(imageId),
        },
        title: cell.path || cell.display || col,
      }
    })
    .filter(Boolean)
}

function openPreview(pathCellValue, row) {
  if (!pathCellValue?.image_info_id) return
  if (rightTab.value === 'sql') {
    selectSqlPreviewRow(row, { focusBrowse: true })
    return
  }
  selectPreviewRow(row, { focusPanel: true })
}

function syncBrowseTableHeight() {
  const wrap = tableWrapRef.value
  if (wrap) {
    let available = wrap.clientHeight
    if (available <= 0) {
      available = wrap.parentElement?.clientHeight ?? 0
    }
    if (available > 200) {
      tableHeight.value = Math.max(200, Math.floor(available) - TABLE_SCROLLBAR_GUTTER)
      return
    }
  }

  const reservedTop = 56 + 16 + 16 + 20 + 12 + 40 + 72 + 48 + 36 + 210
  tableHeight.value = Math.max(420, window.innerHeight - reservedTop - TABLE_SCROLLBAR_GUTTER)
}

function syncTableHeight() {
  syncBrowseTableHeight()
}

function syncScrollLeft(from, to) {
  if (!from || !to) return
  if (from.scrollLeft !== to.scrollLeft) {
    to.scrollLeft = from.scrollLeft
  }
}

function onSqlTableScroll(event) {
  if (sqlHScrollLock) return
  sqlHScrollLock = true
  syncScrollLeft(event.target, sqlHBarRef.value)
  requestAnimationFrame(() => {
    sqlHScrollLock = false
  })
}

function onSqlHBarScroll(event) {
  if (sqlHScrollLock) return
  sqlHScrollLock = true
  syncScrollLeft(event.target, sqlTableWrapRef.value)
  requestAnimationFrame(() => {
    sqlHScrollLock = false
  })
}

function onBrowseTableScroll(event) {
  if (browseHScrollLock) return
  browseHScrollLock = true
  syncScrollLeft(event.target, browseHBarRef.value)
  requestAnimationFrame(() => {
    browseHScrollLock = false
  })
}

function onBrowseHBarScroll(event) {
  if (browseHScrollLock) return
  browseHScrollLock = true
  syncScrollLeft(event.target, tableWrapRef.value)
  requestAnimationFrame(() => {
    browseHScrollLock = false
  })
}

function resetSqlHorizontalScroll() {
  if (sqlTableWrapRef.value) sqlTableWrapRef.value.scrollLeft = 0
  if (sqlHBarRef.value) sqlHBarRef.value.scrollLeft = 0
}

function layoutTableRefs() {
  tableRef.value?.doLayout?.()
  sqlTableRef.value?.doLayout?.()
}

function setupSqlTableViewport() {
  setupTableViewport()
}

function setupTableViewport() {
  nextTick(() => {
    syncTableHeight()
    if (tableWrapRef.value || sqlTableWrapRef.value) {
      if (!resizeObserver) {
        resizeObserver = new ResizeObserver(() => {
          syncTableHeight()
          layoutTableRefs()
        })
      }
      resizeObserver.disconnect()
      if (tableWrapRef.value) {
        resizeObserver.observe(tableWrapRef.value)
      }
      if (sqlTableWrapRef.value) {
        resizeObserver.observe(sqlTableWrapRef.value)
      }
    }
    bindTableScroll()
    layoutTableRefs()
  })
}

function getTableScrollElement() {
  const table = tableRef.value
  if (!table?.$refs?.bodyWrapper) return null
  return (
    table.$refs.bodyWrapper.querySelector('.el-scrollbar__wrap')
    || table.$refs.bodyWrapper
  )
}

function onTableBodyScroll(event) {
  const el = event.target
  if (!el || loadingRows.value || loadingMore.value || !hasMore.value) return
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  if (distance <= SCROLL_LOAD_DISTANCE) {
    loadMore()
  }
}

function bindTableScroll() {
  unbindTableScroll()
  nextTick(() => {
    const el = getTableScrollElement()
    if (!el) return
    tableScrollEl = el
    el.addEventListener('scroll', onTableBodyScroll, { passive: true })
  })
}

function unbindTableScroll() {
  if (tableScrollEl) {
    tableScrollEl.removeEventListener('scroll', onTableBodyScroll)
    tableScrollEl = null
  }
}

function persistBrowseUiState() {
  writeBrowseUiState({
    activeViewId: activeViewId.value,
    rightTab: rightTab.value,
    selectedPk: rowIdentityKey(selectedRow.value),
    catalog: selectedCatalogObject.value
      ? {
          id: selectedCatalogObject.value.id,
          label: selectedCatalogObject.value.label,
          database: selectedCatalogObject.value.database,
          objectType: selectedCatalogObject.value.objectType,
          blobColumns: selectedCatalogObject.value.blobColumns || [],
          nodeType: 'object',
          connection: selectedCatalogObject.value.connection || {},
        }
      : null,
  })
}

function restoreBrowseUiState() {
  const saved = readBrowseUiState()
  if (!saved) return

  if (saved.catalog?.nodeType === 'object') {
    selectedCatalogObject.value = saved.catalog
  }
  if (saved.rightTab === 'sql' || saved.rightTab === 'browse') {
    rightTab.value = saved.rightTab
  }
  if (saved.selectedPk) {
    pendingRestorePk.value = saved.selectedPk
  }
  if (saved.activeViewId && views.value.some((v) => v.id === saved.activeViewId)) {
    activeViewId.value = saved.activeViewId
  }
}

async function loadViews() {
  loadingViews.value = true
  try {
    const res = await callWithRetry(() => listBlobTableViewsApi())
    views.value = res.data || []
    if (activeViewId.value && !views.value.some((v) => v.id === activeViewId.value)) {
      activeViewId.value = null
    }
    await loadMigrationSources()
    await loadMapStats()
  } catch (err) {
    views.value = []
    ElMessage.error(err.message || '加载配置失败')
  } finally {
    loadingViews.value = false
  }
}

async function loadRows({ append = false, includeTotal = !append } = {}) {
  if (!activeViewId.value) {
    columns.value = []
    tableRows.value = []
    total.value = -1
    hasMore.value = false
    selectedRow.value = null
    loadingRows.value = false
    loadingMore.value = false
    return
  }

  const seq = ++rowsLoadSeq
  const restorePk = !append ? (pendingRestorePk.value || rowIdentityKey(selectedRow.value)) : ''
  if (!append) {
    pendingRestorePk.value = ''
  }

  if (append) {
    if (!hasMore.value || loadingMore.value || loadingRows.value) return
    loadingMore.value = true
  } else {
    loadingRows.value = true
    offset.value = 0
    tableRows.value = []
  }

  try {
    const res = await callWithRetry(() => fetchBlobTableViewRowsApi(activeViewId.value, {
      offset: append ? offset.value : 0,
      limit: PAGE_SIZE,
      includeTotal,
    }))
    if (seq !== rowsLoadSeq) return

    const data = res.data || {}
    columns.value = data.columns || []
    const rows = data.rows || []
    if (append) {
      tableRows.value = [...tableRows.value, ...rows]
    } else {
      tableRows.value = rows
    }
    offset.value = (append ? offset.value : 0) + rows.length
    const nextTotal = Number(data.total)
    if (!Number.isNaN(nextTotal) && nextTotal >= 0) {
      total.value = nextTotal
    } else if (!append) {
      total.value = -1
    }
    hasMore.value = Boolean(data.has_more)
    if (!append) {
      if (restorePk) {
        const found = tableRows.value.find((row) => rowIdentityKey(row) === restorePk)
        selectPreviewRow(found ?? tableRows.value[0] ?? null)
      } else {
        autoSelectFirstRow()
      }
      if (!includeTotal && tableRows.value.length) {
        void loadRowTotal(seq)
      }
    }
  } catch (err) {
    if (seq !== rowsLoadSeq) return
    if (!append) {
      columns.value = []
      tableRows.value = []
    }
    ElMessage.error(err.message || '加载数据失败')
  } finally {
    if (seq !== rowsLoadSeq) return
    loadingRows.value = false
    loadingMore.value = false
    setupTableViewport()
  }
}

async function loadRowTotal(expectedSeq) {
  if (!activeViewId.value || expectedSeq !== rowsLoadSeq) return
  try {
    const res = await fetchBlobTableViewRowsApi(activeViewId.value, {
      offset: 0,
      limit: 1,
      includeTotal: true,
    })
    if (expectedSeq !== rowsLoadSeq) return
    const nextTotal = Number(res.data?.total)
    if (!Number.isNaN(nextTotal) && nextTotal >= 0) {
      total.value = nextTotal
      hasMore.value = tableRows.value.length < nextTotal
    }
  } catch {
    // total is optional; ignore background count failures
  }
}

async function refreshActiveView() {
  await loadRows({ append: false })
}

async function loadMore() {
  await loadRows({ append: true })
}

async function removeView(row) {
  if (!row?.id) return
  try {
    await ElMessageBox.confirm(`确定删除配置「${row.source_table || row.name}」？`, '确认', { type: 'warning' })
    await deleteBlobTableViewApi(row.id)
    ElMessage.success('已删除')
    if (activeViewId.value === row.id) {
      activeViewId.value = null
    }
    await loadViews()
  } catch {
    // cancelled
  }
}

function statusTagType(status) {
  if (status === 'migrated') return 'success'
  if (status === 'deleted') return 'danger'
  if (status === 'no_data') return 'info'
  return 'info'
}

function statusLabel(status) {
  if (status === 'migrated') return '已迁移'
  if (status === 'deleted') return '已删除'
  if (status === 'no_data') return '无数据'
  return '未迁移'
}

function blobColumnNames() {
  const fromApi = columns.value
    .filter((col) => col.is_path_substitute)
    .map((col) => col.name)
  if (fromApi.length) return fromApi
  return blobColumnsFromView(activeView.value)
}

function blobColumnName() {
  return blobColumnNames()[0] || ''
}

function getRowImageInfoId(row) {
  if (!row) return null
  for (const col of blobColumnNames()) {
    const cell = pathCell(row, col)
    if (cell?.image_info_id) return cell.image_info_id
  }
  return null
}

function syncTableCurrentRow(row) {
  highlightAndScrollTableRow(
    tableRef,
    row,
    (a, b) => a === b,
  )
}

function syncSqlTableCurrentRow(row) {
  const idx = row ? sqlTableData.value.indexOf(row) : -1
  highlightAndScrollTableRow(
    sqlTableRef,
    row,
    (a, b) => a === b || (idx >= 0 && sqlTableData.value.indexOf(a) === idx),
  )
}

watch(tableRows, () => {
  if (selectedRow.value && !tableRows.value.includes(selectedRow.value)) {
    selectedRow.value = null
  }
  setupTableViewport()
})

watch(sqlTableData, () => {
  if (rightTab.value === 'sql') {
    resetSqlHorizontalScroll()
    setupSqlTableViewport()
  }
})

watch(activeViewId, (id, oldId) => {
  if (!browseReady.value || id === oldId) return
  unbindTableScroll()
  if (!id) {
    rowsLoadSeq += 1
    loadingRows.value = false
    loadingMore.value = false
    columns.value = []
    tableRows.value = []
    total.value = -1
    hasMore.value = false
    selectedRow.value = null
    persistBrowseUiState()
    return
  }
  if (oldId) {
    pendingRestorePk.value = ''
    selectedRow.value = null
  }
  void loadRows({ append: false })
  persistBrowseUiState()
})

watch(
  () => activeView.value,
  (view) => {
    if (view) {
      setupTableViewport()
    } else {
      unbindTableScroll()
    }
  },
)

watch(
  () => route.query.viewId,
  (viewId) => {
    const id = Number(viewId)
    if (id && !Number.isNaN(id)) {
      activeViewId.value = id
      rightTab.value = 'browse'
    }
  },
  { immediate: true },
)

watch(
  () => route.query.mode,
  (mode) => {
    if (mode === 'sql') rightTab.value = 'sql'
  },
  { immediate: true },
)

watch(savedViewForSelection, (view) => {
  if (view) {
    refreshSelectionMigrationStats()
  } else {
    selectionMigrationStats.value = null
  }
})

watch(rightTab, (tab) => {
  persistBrowseUiState()
  if (tab === 'browse') {
    setupTableViewport()
    nextTick(() => {
      if (selectedRow.value) {
        syncTableCurrentRow(selectedRow.value)
      }
    })
  } else if (tab === 'sql') {
    setupSqlTableViewport()
    nextTick(() => {
      if (sqlSelectedRow.value) {
        syncSqlTableCurrentRow(sqlSelectedRow.value)
      }
    })
  }
})

async function bootstrapBrowsePage() {
  browseReady.value = false
  await loadViews()
  restoreBrowseUiState()

  const catalog = selectedCatalogObject.value
  if (catalog?.nodeType === 'object') {
    const saved = findSavedViewForCatalogNode(catalog)
    if (saved) {
      await ensureSavedViewDatabaseMatchesCatalog(saved, catalog.database)
      if (!activeViewId.value) {
        activeViewId.value = saved.id
      }
    }
  }

  const routeViewId = Number(route.query.viewId)
  if (routeViewId && !Number.isNaN(routeViewId) && views.value.some((v) => v.id === routeViewId)) {
    activeViewId.value = routeViewId
  }

  browseReady.value = true
  if (activeViewId.value) {
    await loadRows({ append: false })
  }
  persistBrowseUiState()
}

let browseBootstrapped = false
usePageDataRefresh(
  async () => {
    if (!browseBootstrapped) {
      await bootstrapBrowsePage()
      browseBootstrapped = true
      return
    }
    await loadViews()
  },
  {
    isEmpty: () => !views.value.length,
    intervalMs: 2500,
    maxEmptyRetries: 10,
  },
)

onMounted(() => {
  window.addEventListener('resize', syncTableHeight)
})

onUnmounted(() => {
  unbindTableScroll()
  resizeObserver?.disconnect()
  window.removeEventListener('resize', syncTableHeight)
})
</script>

<template>
  <div class="blob-views-page">
    <div class="page-card">
      <h2 class="page-title">数据库模拟</h2>
      <p class="page-desc">
        左侧按连接与数据库查看表与对象；支持保存配置、多图预览，以及在同一页面执行 SQL 查询。
      </p>

      <div class="layout">
        <aside class="view-list-panel">
          <div class="panel-head">
            <span>数据库目录</span>
            <el-button
              link
              type="primary"
              :loading="loadingViews"
              title="刷新目录与表视图"
              @click="catalogTreeKey += 1; loadViews()"
            >
              <el-icon><Refresh /></el-icon>
            </el-button>
          </div>
          <div class="catalog-tree-wrap">
            <el-tree
              :key="catalogTreeKey"
              ref="catalogTreeRef"
              lazy
              :load="loadCatalogTree"
              node-key="id"
              :props="{ label: 'label', isLeaf: 'leaf' }"
              highlight-current
              class="catalog-tree"
              @node-click="onCatalogNodeClick"
            >
              <template #default="{ data }">
                <span class="catalog-node">
                  <span class="catalog-node-label">{{ catalogNodeLabel(data) }}</span>
                  <el-tag
                    v-if="catalogMigrationTag(data)"
                    size="small"
                    :type="catalogMigrationTag(data).type"
                    effect="plain"
                    class="catalog-migration-tag"
                  >
                    {{ catalogMigrationTag(data).text }}
                  </el-tag>
                </span>
              </template>
            </el-tree>
          </div>

          <div v-if="selectedCatalogObject" class="catalog-selection">
            <div class="catalog-selection-title">已选对象</div>
            <div>{{ selectedCatalogObject.database }}.{{ selectedCatalogObject.label }}</div>
            <div class="field-hint">
              {{ selectedCatalogObject.objectType === 'view' ? '数据库视图' : '表' }}
              <template v-if="selectionMigrationHint">
                · {{ selectionMigrationHint }}
              </template>
              <template v-if="savedViewForSelection?.row_count != null">
                · {{ savedViewForSelection.row_count }} 行
              </template>
            </div>
            <div class="catalog-actions">
              <template v-if="!savedViewForSelection">
                <el-button size="small" type="primary" plain @click="openCreateViewDialog">
                  创建配置
                </el-button>
              </template>
              <template v-else>
                <el-button
                  v-if="showMigrateForSelection"
                  size="small"
                  type="primary"
                  :icon="VideoPlay"
                  @click="openMigrateDialog"
                >
                  一键迁移
                </el-button>
                <el-button size="small" type="success" plain @click="openExportDialog">
                  导出到连接
                </el-button>
                <el-button size="small" plain @click="refreshActiveView">刷新</el-button>
                <el-button size="small" type="danger" plain @click="removeView(savedViewForSelection)">
                  删除配置
                </el-button>
                <el-button size="small" plain @click="rightTab = 'sql'">SQL 查询</el-button>
              </template>
            </div>
          </div>
        </aside>

        <main class="data-panel">
          <el-tabs v-model="rightTab" class="right-tabs">
            <el-tab-pane label="表数据" name="browse">
              <div v-if="activeView" class="browse-pane">
                <el-alert
                  v-if="catalogDatabaseMismatch"
                  type="warning"
                  :closable="false"
                  show-icon
                  class="browse-db-mismatch"
                  :title="catalogDatabaseMismatch"
                  description="表数据按配置的库名查询。请重新点击左侧目录中的表，或删除配置后重建。"
                />
                <div class="data-head">
                  <div>
                    <h3>{{ activeView.source_table }}</h3>
                    <p class="field-hint">
                      {{ activeView.db_label || activeView.db_alias }} /
                      {{ activeView.database_name || '（默认库）' }} /
                      {{ activeView.source_table }} · PK {{ activeView.source_pk_column }} ·
                      BLOB → {{ blobColumnNames().join(', ') }}
                      <span v-if="activeView.where_clause"> · WHERE {{ activeView.where_clause }}</span>
                    </p>
                  </div>
                  <div class="data-head-actions">
                    <span class="row-count">
                      已加载 {{ tableRows.length
                      }}<template v-if="total >= 0"> / {{ total }}</template>
                    </span>
                    <el-button :loading="loadingRows" @click="refreshActiveView">刷新</el-button>
                  </div>
                </div>

                <div class="table-panel">
                  <div class="browse-result-list-wrap">
                    <div class="result-table-area">
                      <div
                        ref="tableWrapRef"
                        v-loading="loadingRows && !tableRows.length"
                        class="browse-result-list-scroll"
                        tabindex="0"
                        @scroll="onBrowseTableScroll"
                        @keydown="onPreviewKeydown"
                      >
                        <template v-if="columns.length">
                          <div class="table-h-scroll-inner" :style="browseTableInnerStyle">
                            <el-table
                              ref="tableRef"
                              :data="tableRows"
                              :height="tableHeight"
                              :fit="false"
                              size="small"
                              border
                              stripe
                              highlight-current-row
                              :row-key="getRowKey"
                              class="data-table data-table--wide compact-table"
                              empty-text="无数据"
                              @row-click="onTableRowClick"
                            >
                        <el-table-column
                          v-for="col in columns"
                          :key="col.name"
                          :prop="col.name"
                          :label="col.name"
                          :width="col.is_path_substitute ? 200 : 100"
                          show-overflow-tooltip
                        >
                          <template #default="{ row }">
                            <template v-if="col.is_path_substitute">
                              <div class="path-cell">
                                <el-tag
                                  :type="statusTagType(pathCell(row, col.name)?.status)"
                                  size="small"
                                  class="path-tag"
                                >
                                  {{ statusLabel(pathCell(row, col.name)?.status) }}
                                </el-tag>
                                <span class="path-text">{{ formatCell(row, col.name) }}</span>
                                <el-button
                                  v-if="pathCell(row, col.name)?.image_info_id"
                                  link
                                  type="primary"
                                  :icon="View"
                                  @click="openPreview(pathCell(row, col.name), row)"
                                />
                              </div>
                            </template>
                            <template v-else>
                              {{ formatCell(row, col.name) }}
                            </template>
                          </template>
                        </el-table-column>
                          </el-table>
                          </div>
                        </template>
                        <el-empty v-else-if="!loadingRows" description="无数据" />
                      </div>
                      <div
                        v-if="columns.length"
                        ref="browseHBarRef"
                        class="result-h-scrollbar"
                        @scroll="onBrowseHBarScroll"
                      >
                        <div class="result-h-scrollbar-inner" :style="browseTableInnerStyle" />
                      </div>
                    </div>
                    <div v-if="loadingMore" class="load-more-hint">加载更多…</div>
                    <div v-else-if="tableRows.length && !hasMore" class="load-more-hint muted">已全部加载</div>
                  </div>

                  <div
                    ref="rowPreviewPanelRef"
                    class="row-preview-panel"
                    tabindex="0"
                    @keydown="onPreviewKeydown"
                  >
                    <div class="row-preview-head">
                      <span>行预览</span>
                      <span v-if="selectedRowPreviewItems.length" class="row-preview-count">
                        {{ selectedRowPreviewItems.length }} 张
                      </span>
                      <span
                        v-if="tableRows.length > 1 && selectedPreviewRowIndex >= 0"
                        class="row-preview-count"
                      >
                        第 {{ selectedPreviewRowIndex + 1 }} / {{ tableRows.length }} 行
                      </span>
                      <span v-if="tableRows.length > 1 || hasMore" class="row-preview-hint">
                        点击结果区后 ↑↓←→ 切换行（到底部会自动加载下一页）
                      </span>
                    </div>
                    <div v-if="selectedRowPreviewItems.length" class="row-preview-strip">
                      <div
                        v-for="item in selectedRowPreviewItems"
                        :key="item.column"
                        class="row-preview-card"
                      >
                        <div class="row-preview-label">{{ item.column }}</div>
                        <ImagePreview
                          :key="`${item.cell.image_info_id}-${item.column}`"
                          :image-id="item.cell.image_info_id"
                          :image-path="item.cell.path"
                          :size="112"
                          :lazy="false"
                          clickable
                          @click="openBrowseLightbox(item)"
                        />
                        <div class="row-preview-path" :title="item.title">{{ item.title }}</div>
                        <div class="row-preview-zoom-hint">点击图片放大 · 放大后 ↑↓ 换行</div>
                      </div>
                    </div>
                    <div v-else class="row-preview-empty">
                      点击表格行切换选中；已迁移的图片会显示在下方（无图/未迁移行仅高亮表格行）
                    </div>
                  </div>
                </div>
              </div>
              <el-empty v-else description="请在左侧目录选择表或视图" />
            </el-tab-pane>

            <el-tab-pane label="SQL 查询" name="sql">
              <div class="sql-pane">
                <div class="sql-pane-head">
                  <div class="sql-editor-wrap">
                    <SqlEditor v-model="sqlText" @execute="handleSqlExecute" />
                  </div>
                  <div class="sql-toolbar">
                    <el-button :loading="sqlValidating" @click="handleSqlValidate">校验</el-button>
                    <el-button type="primary" :loading="sqlExecuting" :icon="VideoPlay" @click="handleSqlExecute">
                      执行
                    </el-button>
                    <span v-if="sqlResult" class="sql-meta">
                      {{ sqlResult.row_count }} 行 · {{ sqlResult.elapsed_ms }}ms
                      <span v-if="sqlResult.truncated">（已截断）</span>
                    </span>
                  </div>
                  <el-alert v-if="sqlError" :title="sqlError" type="error" show-icon :closable="false" class="sql-error" />
                </div>

                <div v-if="sqlTableData.length" class="table-panel sql-results-panel">
                  <div class="sql-result-list-wrap">
                    <div class="result-table-area">
                      <div
                        ref="sqlTableWrapRef"
                        class="sql-result-list-scroll"
                        tabindex="0"
                        @scroll="onSqlTableScroll"
                        @keydown="onSqlPreviewKeydown"
                      >
                        <div class="table-h-scroll-inner" :style="sqlTableInnerStyle">
                          <el-table
                            ref="sqlTableRef"
                            :data="sqlTableData"
                            :fit="false"
                            size="small"
                            border
                            stripe
                            highlight-current-row
                            :row-key="getSqlRowKey"
                            class="data-table data-table--wide compact-table"
                            @row-click="onSqlTableRowClick"
                          >
                        <el-table-column
                          v-for="col in sqlResult.columns"
                          :key="col"
                          :prop="col"
                          :label="col"
                          :width="sqlColumnWidth(col)"
                          show-overflow-tooltip
                        >
                          <template #default="{ row }">
                            <template v-if="sqlIsPathColumn(col) || sqlPathCell(row, col)">
                              <div class="path-cell">
                                <el-tag
                                  :type="statusTagType(sqlPathCell(row, col)?.status)"
                                  size="small"
                                  class="path-tag"
                                >
                                  {{ statusLabel(sqlPathCell(row, col)?.status) }}
                                </el-tag>
                                <span class="path-text">{{ sqlFormatCell(row, col) }}</span>
                                <el-button
                                  v-if="sqlPathCell(row, col)?.image_info_id"
                                  link
                                  type="primary"
                                  size="small"
                                  @click.stop="openPreview(sqlPathCell(row, col), row)"
                                >
                                  预览
                                </el-button>
                              </div>
                            </template>
                            <template v-else>
                              {{ formatCellValue(row[col]) }}
                            </template>
                          </template>
                          </el-table-column>
                          </el-table>
                        </div>
                      </div>
                      <div
                        ref="sqlHBarRef"
                        class="result-h-scrollbar"
                        @scroll="onSqlHBarScroll"
                      >
                        <div class="result-h-scrollbar-inner" :style="sqlTableInnerStyle" />
                      </div>
                    </div>
                  </div>

                  <div
                    ref="sqlPreviewPanelRef"
                    class="row-preview-panel sql-preview-panel"
                    tabindex="0"
                    @keydown="onSqlPreviewKeydown"
                  >
                    <div class="row-preview-head">
                      <span>SQL 结果预览</span>
                      <span v-if="sqlSelectedPreviewItems.length" class="row-preview-count">
                        {{ sqlSelectedPreviewItems.length }} 张
                      </span>
                      <span
                        v-if="sqlTableData.length > 1 && selectedSqlRowIndex >= 0"
                        class="row-preview-count"
                      >
                        第 {{ selectedSqlRowIndex + 1 }} / {{ sqlTableData.length }} 行
                      </span>
                      <span v-if="sqlTableData.length > 1" class="row-preview-hint">
                        点击结果区后 ↑↓←→ 切换行
                      </span>
                    </div>
                    <div v-if="sqlSelectedPreviewItems.length" class="row-preview-strip">
                      <div
                        v-for="item in sqlSelectedPreviewItems"
                        :key="item.column"
                        class="row-preview-card"
                      >
                        <div class="row-preview-label">{{ item.column }}</div>
                        <ImagePreview
                          :key="`${item.cell.image_info_id}-${item.column}`"
                          :image-id="item.cell.image_info_id"
                          :image-path="item.cell.path"
                          :size="120"
                          :lazy="false"
                          clickable
                          @click="openBrowseLightbox(item)"
                        />
                        <div class="row-preview-path" :title="item.title">{{ item.title }}</div>
                        <div class="row-preview-zoom-hint">点击图片放大 · 放大后 ↑↓ 换行</div>
                      </div>
                    </div>
                    <div v-else class="row-preview-empty">
                      点击表格行切换选中；已迁移的图片会显示在下方（无图/未迁移行仅高亮表格行）
                    </div>
                  </div>
                </div>
                <el-empty v-else-if="!sqlExecuting" description="执行 SELECT 后在此显示结果" />
              </div>
            </el-tab-pane>
          </el-tabs>
        </main>
      </div>
    </div>

    <el-dialog v-model="createViewDialogVisible" title="从目录创建配置" width="560px">
      <el-form label-width="110px">
        <el-form-item label="名称">
          <el-input v-model="createViewForm.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="主键列">
          <el-input v-model="createViewForm.sourcePkColumn" maxlength="64" />
        </el-form-item>
        <el-form-item label="BLOB 列" required>
          <el-select v-model="createViewForm.blobColumns" multiple collapse-tags style="width: 100%">
            <el-option
              v-for="col in selectedCatalogObject?.blobColumns || []"
              :key="col.column"
              :label="col.column"
              :value="col.column"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="selectedCatalogObject?.objectType === 'view'" label="路径映射">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="JOIN 视图会根据建视图 SQL 自动推断每个 BLOB 列对应的基表与关联键"
          />
        </el-form-item>
        <el-form-item label="WHERE">
          <el-input v-model="createViewForm.whereClause" placeholder="不含 WHERE 关键字" />
        </el-form-item>

        <el-divider content-position="left">迁移（可选）</el-divider>
        <el-form-item label="同时配置迁移">
          <el-switch v-model="createViewForm.alsoMigrate" />
          <span class="field-hint inline-hint">保存浏览配置的同时创建迁移任务配置</span>
        </el-form-item>
        <template v-if="createViewForm.alsoMigrate">
          <el-form-item label="文件名列">
            <el-input v-model="createViewForm.nameColumn" placeholder="可选，用于生成文件名" maxlength="64" />
          </el-form-item>
          <el-form-item label="后缀列">
            <el-input v-model="createViewForm.suffixColumn" placeholder="可选，如 jpg/png" maxlength="64" />
          </el-form-item>
          <el-form-item label="标签">
            <el-input v-model="createViewForm.tags" placeholder="可选" maxlength="500" />
          </el-form-item>
          <el-form-item label="立即开始">
            <el-switch v-model="createViewForm.startMigration" />
            <span class="field-hint inline-hint">有待迁移数据时自动启动后台任务</span>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="createViewDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createViewSaving" @click="submitCreateView">
          {{ createViewForm.alsoMigrate && createViewForm.startMigration ? '创建并开始迁移' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <ImageLightbox
      v-model="browseLightboxOpen"
      :image-id="browseLightboxImageId"
      :image-path="browseLightboxPath"
      :title="browseLightboxTitle"
      @prev="onBrowseLightboxPrev"
      @next="onBrowseLightboxNext"
    />

    <el-dialog v-model="migrateDialogVisible" title="一键迁移" width="520px">
      <p class="field-hint migrate-dialog-desc">
        将「{{ savedViewForSelection?.source_table }}」的 BLOB 数据迁移到图片库，并启动后台任务。
      </p>
      <el-form label-width="110px">
        <el-form-item label="文件名列">
          <el-input v-model="migrateForm.nameColumn" placeholder="可选，用于生成文件名" maxlength="64" />
        </el-form-item>
        <el-form-item label="后缀列">
          <el-input v-model="migrateForm.suffixColumn" placeholder="可选，如 jpg/png" maxlength="64" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="migrateForm.tags" placeholder="可选" maxlength="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="migrateDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="migrateSaving" @click="submitSavedViewMigration">
          开始迁移
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="exportDialogVisible"
      title="导出到连接"
      width="560px"
      @close="closeExportDialog"
    >
      <p class="field-hint migrate-dialog-desc">
        将「{{ savedViewForSelection?.source_table }}」写成目标库物理表（BLOB 列填路径）。
        点击开始后任务在<strong>后台运行</strong>，可关闭本窗并去做其他事；右下角可看进度。
      </p>
      <el-alert
        v-if="exportError"
        type="error"
        :closable="false"
        show-icon
        class="export-status-alert"
        :title="exportError"
      />
      <el-form label-width="110px">
        <el-form-item label="目标连接" required>
          <el-select
            v-model="exportForm.targetKey"
            placeholder="选择目标库 / 连接"
            filterable
            :loading="loadingExportTargets"
            :empty-text="loadingExportTargets ? '加载中…' : '暂无目标，请先在迁移页添加连接'"
            style="width: 100%"
            @change="onExportTargetChange"
          >
            <el-option
              v-for="t in exportTargets"
              :key="t.key"
              :label="t.label"
              :value="t.key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="目标数据库" required>
          <el-select
            v-model="exportForm.database"
            placeholder="选择数据库"
            filterable
            :loading="loadingExportDatabases"
            :empty-text="loadingExportDatabases ? '加载中…' : '请先选择目标连接'"
            style="width: 100%"
          >
            <el-option v-for="db in exportDatabases" :key="db" :label="db" :value="db" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标表名" required>
          <el-input v-model="exportForm.tableName" maxlength="64" placeholder="默认与源表同名" />
        </el-form-item>
        <el-form-item label="已存在时">
          <el-radio-group v-model="exportForm.ifExists">
            <el-radio value="fail">失败（不覆盖）</el-radio>
            <el-radio value="replace">替换（删表重建）</el-radio>
            <el-radio value="truncate">清空后写入</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeExportDialog">取消</el-button>
        <el-button type="primary" :loading="exportSaving" @click="submitExportToConnection">
          后台开始导出
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.blob-views-page {
  max-width: none;
  margin: -8px -12px -12px;
  width: calc(100% + 24px);
  height: calc(100vh - var(--header-height) - 36px - 8px);
  min-height: 720px;
  display: flex;
  flex-direction: column;
}

.page-card {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 12px 16px;
  box-shadow: 0 1px 4px rgb(0 0 0 / 6%);
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.page-title {
  margin: 0 0 6px;
  font-size: 20px;
  flex-shrink: 0;
}

.page-desc {
  margin: 0 0 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  flex-shrink: 0;
  font-size: 13px;
}

.layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  flex: 1;
  min-height: 0;
}

.catalog-tree-wrap {
  flex: 1;
  min-height: 120px;
  min-width: 0;
  overflow: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  scrollbar-width: thin;
}

.catalog-tree-wrap::-webkit-scrollbar {
  height: 10px;
  width: 8px;
}

.catalog-tree-wrap::-webkit-scrollbar-thumb {
  border-radius: 4px;
  background: var(--el-border-color);
}

.catalog-tree {
  display: inline-block;
  min-width: 100%;
  width: max-content;
  padding: 4px 0;
  box-sizing: border-box;
}

.catalog-tree :deep(.el-tree-node) {
  white-space: nowrap;
}

.catalog-tree :deep(.el-tree-node__content) {
  height: auto;
  min-height: 24px;
  overflow: visible;
  width: max-content;
  max-width: none;
}

.catalog-tree :deep(.el-tree-node__label) {
  overflow: visible;
  flex: 0 0 auto;
  max-width: none;
}

.catalog-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  white-space: nowrap;
  width: max-content;
}

.catalog-node-label {
  flex-shrink: 0;
}

.catalog-migration-tag {
  flex-shrink: 0;
  height: 18px;
  padding: 0 4px;
  font-size: 10px;
}

.catalog-selection-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  margin-bottom: 4px;
}

.catalog-selection {
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  font-size: 12px;
  flex-shrink: 0;
}

.catalog-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.right-tabs {
  flex: 1;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.right-tabs :deep(.el-tabs__header) {
  flex-shrink: 0;
  margin-bottom: 8px;
}

.right-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.right-tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.browse-pane {
  flex: 1;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.browse-db-mismatch {
  margin-bottom: 12px;
  flex-shrink: 0;
}

.sql-preview-panel {
  margin-top: 0;
}

.sql-pane {
  flex: 1;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sql-pane-head {
  flex-shrink: 0;
}

.sql-results-panel {
  margin-top: 8px;
  flex: 1;
  min-height: 0;
}

.sql-editor-wrap {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 8px;
}

.sql-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.sql-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.sql-error {
  margin-bottom: 8px;
}

.inline-hint {
  margin-left: 8px;
}

.view-list-panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow: hidden;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  flex-shrink: 0;
}

.data-panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.data-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  flex-shrink: 0;
}

.data-head h3 {
  margin: 0 0 4px;
  font-size: 16px;
}

.field-hint {
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.category-row {
  display: flex;
  gap: 8px;
  width: 100%;
  align-items: center;
}

.data-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.row-count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.table-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
}

.table-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 上方数据列表（与底部图片预览区分开） */
.sql-result-list-wrap,
.browse-result-list-wrap {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.result-table-area {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  overflow: hidden;
}

.browse-result-list-scroll {
  flex: 1;
  min-width: 0;
  min-height: 180px;
  overflow: auto;
  overscroll-behavior: contain;
  outline: none;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.sql-result-list-scroll {
  flex: 1;
  min-width: 0;
  min-height: 180px;
  overflow: auto;
  overscroll-behavior: contain;
  outline: none;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.sql-result-list-scroll::-webkit-scrollbar,
.browse-result-list-scroll::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}

.result-h-scrollbar {
  flex-shrink: 0;
  height: 14px;
  overflow-x: auto;
  overflow-y: hidden;
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-lighter);
  scrollbar-width: thin;
}

.result-h-scrollbar::-webkit-scrollbar {
  height: 12px;
}

.result-h-scrollbar::-webkit-scrollbar-thumb {
  border-radius: 6px;
  background: var(--el-border-color-darker);
}

.result-h-scrollbar-inner {
  height: 1px;
}

.sql-result-list-scroll:focus,
.browse-result-list-scroll:focus {
  box-shadow: inset 0 0 0 1px var(--el-color-primary-light-5);
}

.browse-result-list-scroll :deep(.el-scrollbar__bar.is-horizontal),
.sql-result-list-scroll :deep(.el-scrollbar__bar.is-horizontal) {
  display: none !important;
}

.sql-result-list-scroll :deep(.el-table__inner-wrapper),
.browse-result-list-scroll :deep(.el-table__inner-wrapper) {
  overflow: visible !important;
}

.sql-result-list-scroll :deep(.el-table__body-wrapper),
.sql-result-list-scroll :deep(.el-table__header-wrapper),
.browse-result-list-scroll :deep(.el-table__header-wrapper) {
  overflow: visible !important;
}

.browse-result-list-scroll :deep(.el-table__body-wrapper) {
  overflow-x: visible !important;
}

.result-table-area .table-h-scroll-inner {
  width: max-content;
  min-width: 100%;
}

.result-table-area .table-h-scroll-inner :deep(.el-table) {
  width: 100% !important;
}

.row-preview-panel {
  flex: 0 0 200px;
  min-height: 160px;
  max-height: 220px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  min-width: 0;
  outline: none;
}

.row-preview-panel:focus-visible {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-7);
}

.row-preview-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 6px;
  flex-shrink: 0;
}

.row-preview-hint {
  margin-left: auto;
  font-size: 11px;
  font-weight: normal;
  color: var(--el-text-color-secondary);
}

.row-preview-count {
  font-weight: normal;
  color: var(--el-text-color-secondary);
}

.row-preview-strip {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 10px;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 4px;
  scrollbar-width: thin;
}

.row-preview-strip::-webkit-scrollbar {
  height: 8px;
}

.row-preview-strip::-webkit-scrollbar-thumb {
  border-radius: 4px;
  background: var(--el-border-color);
}

.row-preview-card {
  flex: 0 0 auto;
  width: 128px;
  text-align: center;
}

.row-preview-label {
  font-size: 11px;
  font-weight: 600;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-preview-path {
  margin-top: 4px;
  font-size: 10px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-preview-zoom-hint {
  margin-top: 2px;
  font-size: 10px;
  color: var(--el-color-primary);
  line-height: 1.2;
}

.row-preview-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.table-viewport {
  flex: 1;
  min-height: 240px;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  outline: none;
}

.table-viewport--native-scroll-x {
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}

.table-viewport--native-scroll {
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.table-viewport--native-scroll-x::-webkit-scrollbar,
.table-viewport--native-scroll::-webkit-scrollbar {
  width: 10px;
  height: 12px;
}

.table-viewport--native-scroll-x::-webkit-scrollbar-thumb,
.table-viewport--native-scroll::-webkit-scrollbar-thumb {
  border-radius: 6px;
  background: var(--el-border-color-darker);
}

.table-h-scroll-inner {
  width: max-content;
  min-width: 100%;
  height: 100%;
}

.table-viewport--native-scroll-x :deep(.el-scrollbar__bar.is-horizontal),
.table-viewport--native-scroll :deep(.el-scrollbar__bar.is-horizontal) {
  display: none !important;
}

.table-viewport--native-scroll :deep(.el-table__body-wrapper),
.table-viewport--native-scroll :deep(.el-table__header-wrapper) {
  overflow: visible !important;
}

.table-viewport:focus {
  box-shadow: inset 0 0 0 1px var(--el-color-primary-light-5);
}

.table-viewport :deep(.el-scrollbar__bar.is-vertical) {
  width: 10px;
  right: 0;
  z-index: 4;
}

.data-table {
  width: 100%;
}

.data-table--wide {
  width: auto !important;
  max-width: none !important;
}

.data-table--wide :deep(.el-table__header table),
.data-table--wide :deep(.el-table__body table) {
  width: 100% !important;
  table-layout: fixed !important;
}

.compact-table :deep(.el-table__cell) {
  padding: 1px 0;
  font-size: 12px;
}

.compact-table :deep(.el-table__header .el-table__cell) {
  padding: 3px 0;
  font-size: 12px;
}

.compact-table :deep(.el-table__body tr) {
  height: 24px;
}

.compact-table :deep(.el-tag) {
  transform: scale(0.9);
}

.data-table :deep(.el-table__header-wrapper) {
  position: sticky;
  top: 0;
  z-index: 2;
}

.path-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.path-tag {
  flex-shrink: 0;
}

.path-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

.load-more-hint {
  text-align: center;
  padding: 8px 10px 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.load-more-hint.muted {
  color: var(--el-text-color-placeholder);
}

.export-status-alert {
  margin-bottom: 12px;
}
.export-progress-panel {
  padding: 12px 4px 4px;
  text-align: center;
}
.export-progress-title {
  margin: 14px 0 6px;
  font-size: 15px;
  font-weight: 600;
}
.export-progress-meta {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.export-success-panel :deep(.el-result) {
  padding: 8px 0 0;
}
.export-result-lines {
  display: flex;
  flex-direction: column;
  gap: 6px;
  text-align: left;
  font-size: 13px;
}
.export-warn {
  color: var(--el-color-warning);
}

@media (max-width: 960px) {
  .blob-views-page {
    height: auto;
    min-height: calc(100vh - var(--header-height) - 32px);
  }

  .layout {
    grid-template-columns: 1fr;
  }

  .table-viewport {
    min-height: 420px;
  }
}
</style>
