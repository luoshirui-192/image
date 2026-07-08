<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, VideoPlay, View } from '@element-plus/icons-vue'
import ImagePreview from '@/components/ImagePreview.vue'
import SqlEditor from '@/components/SqlEditor.vue'
import {
  createBlobTableViewApi,
  deleteBlobTableViewApi,
  fetchBlobTableViewRowsApi,
  getBlobCatalogObjectApi,
  listBlobCatalogConnectionsApi,
  listBlobCatalogDatabasesApi,
  listBlobCatalogObjectsApi,
  listBlobTableViewsApi,
} from '@/api/images'
import {
  executeSqlApi,
  findPathColumn,
  formatCellValue,
  rowsToRecords,
  validateSqlApi,
} from '@/api/sql'
import { highlightAndScrollTableRow } from '@/utils/tableScroll'

const route = useRoute()
const router = useRouter()

const views = ref([])
const loadingViews = ref(false)
const activeViewId = ref(null)

const columns = ref([])
const tableRows = ref([])
const total = ref(0)
const offset = ref(0)
const hasMore = ref(false)
const loadingRows = ref(false)
const loadingMore = ref(false)

const tableRef = ref(null)
const tableWrapRef = ref(null)
const rowPreviewPanelRef = ref(null)
const tableHeight = ref(520)
let tableScrollEl = null
let resizeObserver = null

const PAGE_SIZE = 80
const SCROLL_LOAD_DISTANCE = 120

const browseReady = ref(false)
let rowsLoadSeq = 0

const selectedRow = ref(null)

const activeView = computed(() => views.value.find((v) => v.id === activeViewId.value) || null)

const selectedRowPreviewItems = computed(() => {
  if (!selectedRow.value) return []
  return rowPreviewCells(selectedRow.value)
})

const previewableTableRows = computed(() =>
  tableRows.value.filter((row) => rowPreviewCells(row).length > 0),
)

const selectedPreviewRowIndex = computed(() => {
  if (!selectedRow.value) return -1
  const key = getRowKey(selectedRow.value)
  return previewableTableRows.value.findIndex((row) => getRowKey(row) === key)
})

let previewWheelLocked = false

const loadingCatalog = ref(false)
const selectedCatalogObject = ref(null)
const viewsVersion = ref(0)

const rightTab = ref('browse')

const sqlText = ref('')
const sqlExecuting = ref(false)
const sqlValidating = ref(false)
const sqlResult = ref(null)
const sqlError = ref('')

const createViewDialogVisible = ref(false)
const createViewSaving = ref(false)
const createViewForm = reactive({
  name: '',
  sourcePkColumn: 'id',
  blobColumns: [],
  whereClause: '',
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

const sqlTableData = computed(() => {
  if (!sqlResult.value) return []
  return rowsToRecords(sqlResult.value.columns, sqlResult.value.rows)
})

const sqlPathColumn = computed(() => {
  if (!sqlResult.value) return null
  return findPathColumn(sqlResult.value.columns, sqlResult.value.rows)
})

function catalogNodeLabel(data) {
  if (data.nodeType === 'connection') return data.label
  if (data.nodeType === 'database') {
    return data.isMigrationTarget ? `${data.label}（迁移库）` : data.label
  }
  if (data.nodeType === 'object') {
    const typeLabel = data.objectType === 'view' ? '数据库视图' : '表'
    const blobs = (data.blobColumns || []).map((item) => item.column).join(', ')
    return `${data.label} [${typeLabel}]${blobs ? ` · ${blobs}` : ''}`
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
  return views.value.find((view) => viewCatalogKey(view) === key) || null
}

const savedViewForSelection = computed(() => {
  if (!selectedCatalogObject.value) return null
  return findSavedViewForCatalogNode(selectedCatalogObject.value)
})

async function loadCatalogTree(root, resolve) {
  loadingCatalog.value = true
  try {
    if (root.level === 0) {
      const res = await listBlobCatalogConnectionsApi()
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
      const res = await listBlobCatalogDatabasesApi(params)
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
      const res = await listBlobCatalogObjectsApi(params)
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
    return
  }
  if (data.nodeType !== 'object') return
  selectedCatalogObject.value = data
  sqlText.value = `SELECT * FROM \`${data.label}\` LIMIT 80`
  const saved = findSavedViewForCatalogNode(data)
  if (saved) {
    activeViewId.value = saved.id
    rightTab.value = 'browse'
  } else {
    activeViewId.value = null
  }
}

function goMigrateWithCatalog() {
  if (!selectedCatalogObject.value) {
    router.push('/blob-migrate')
    return
  }
  const obj = selectedCatalogObject.value
  const conn = obj.connection || {}
  router.push({
    path: '/blob-migrate',
    query: {
      dbAlias: conn.alias || '',
      sourceTable: obj.label,
      database: obj.database || '',
      objectType: obj.objectType || 'table',
    },
  })
}

async function openCreateViewDialog() {
  if (!selectedCatalogObject.value) return
  const obj = selectedCatalogObject.value
  const conn = obj.connection || {}
  createViewForm.name = obj.label
  createViewForm.blobColumns = (obj.blobColumns || []).map((item) => item.column)
  createViewForm.whereClause = ''
  createViewForm.sourcePkColumn = 'id'
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
  createViewSaving.value = true
  try {
    const res = await createBlobTableViewApi({
      name: createViewForm.name.trim() || obj.label,
      db_alias: conn.alias,
      database_name: obj.database,
      source_table: obj.label,
      source_object_type: obj.objectType || 'table',
      source_pk_column: createViewForm.sourcePkColumn.trim() || 'id',
      blob_columns: [...createViewForm.blobColumns],
      where_clause: createViewForm.whereClause.trim(),
    })
    ElMessage.success('配置已创建')
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
    await validateSqlApi(sql, browseContext.value)
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
    const res = await executeSqlApi(sql, browseContext.value)
    sqlResult.value = res.data
  } catch (err) {
    sqlResult.value = null
    sqlError.value = err.message || '执行失败'
  } finally {
    sqlExecuting.value = false
  }
}

function formatCell(row, colName) {
  const value = row[colName]
  if (value && typeof value === 'object' && 'display' in value) {
    return value.display
  }
  if (value == null) return '—'
  return String(value)
}

function pathCell(row, colName) {
  const value = row[colName]
  if (value && typeof value === 'object') return value
  return null
}

function autoSelectFirstRow() {
  const row = previewableTableRows.value[0] ?? null
  selectPreviewRow(row)
}

function selectPreviewRow(row, { focusPanel = false } = {}) {
  selectedRow.value = row
  syncTableCurrentRow(row)
  if (focusPanel) {
    nextTick(() => rowPreviewPanelRef.value?.focus())
  }
}

function goPrevPreviewRow() {
  const rows = previewableTableRows.value
  if (rows.length <= 1) return
  const idx = selectedPreviewRowIndex.value
  if (idx <= 0) return
  selectPreviewRow(rows[idx - 1])
}

function goNextPreviewRow() {
  const rows = previewableTableRows.value
  if (rows.length <= 1) return
  const idx = selectedPreviewRowIndex.value
  if (idx < 0 || idx >= rows.length - 1) return
  selectPreviewRow(rows[idx + 1])
}

function onPreviewKeydown(event) {
  if (!previewableTableRows.value.length) return
  if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    event.preventDefault()
    goPrevPreviewRow()
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    event.preventDefault()
    goNextPreviewRow()
  }
}

function onPreviewWheel(event) {
  const rows = previewableTableRows.value
  if (rows.length <= 1 || previewWheelLocked) return
  if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return
  event.preventDefault()
  previewWheelLocked = true
  window.setTimeout(() => {
    previewWheelLocked = false
  }, 200)
  if (event.deltaY > 0) {
    goNextPreviewRow()
  } else if (event.deltaY < 0) {
    goPrevPreviewRow()
  }
}

function onTableRowClick(row, _column, event) {
  if (event?.target?.closest?.('button, a, .el-button')) return
  selectPreviewRow(row, { focusPanel: true })
}

function rowPreviewCells(row) {
  return blobColumnNames()
    .map((col) => {
      const cell = pathCell(row, col)
      if (!cell?.image_info_id || cell.status !== 'migrated') return null
      return {
        column: col,
        cell,
        title: cell.path || cell.display || col,
      }
    })
    .filter(Boolean)
}

function openPreview(pathCellValue, row) {
  if (!pathCellValue?.image_info_id) return
  selectPreviewRow(row, { focusPanel: true })
}

function syncTableHeight() {
  const wrap = tableWrapRef.value
  const main = wrap?.parentElement
  if (wrap && main) {
    let available = wrap.clientHeight
    if (available <= 0) {
      const hint = main.querySelector('.load-more-hint')
      available = main.clientHeight - (hint?.offsetHeight ?? 0)
    }
    if (available > 200) {
      tableHeight.value = Math.floor(available)
      return
    }
  }

  const reservedTop = 56 + 16 + 16 + 20 + 12 + 40 + 72 + 48 + 36 + 210
  tableHeight.value = Math.max(420, window.innerHeight - reservedTop)
}

function setupTableViewport() {
  nextTick(() => {
    syncTableHeight()
    if (tableWrapRef.value) {
      if (!resizeObserver) {
        resizeObserver = new ResizeObserver(() => {
          syncTableHeight()
        })
      }
      resizeObserver.disconnect()
      resizeObserver.observe(tableWrapRef.value)
    }
    bindTableScroll()
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

async function loadViews() {
  loadingViews.value = true
  try {
    const res = await listBlobTableViewsApi()
    views.value = res.data || []
    viewsVersion.value += 1
    if (activeViewId.value && !views.value.some((v) => v.id === activeViewId.value)) {
      activeViewId.value = null
    }
  } catch (err) {
    views.value = []
    ElMessage.error(err.message || '加载配置失败')
  } finally {
    loadingViews.value = false
  }
}

async function loadRows({ append = false } = {}) {
  if (!activeViewId.value) {
    columns.value = []
    tableRows.value = []
    total.value = 0
    hasMore.value = false
    selectedRow.value = null
    return
  }

  const seq = ++rowsLoadSeq

  if (append) {
    if (!hasMore.value || loadingMore.value || loadingRows.value) return
    loadingMore.value = true
  } else {
    loadingRows.value = true
    offset.value = 0
    tableRows.value = []
  }

  try {
    const res = await fetchBlobTableViewRowsApi(activeViewId.value, {
      offset: append ? offset.value : 0,
      limit: PAGE_SIZE,
    })
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
    total.value = data.total ?? tableRows.value.length
    hasMore.value = Boolean(data.has_more)
    if (!append) {
      autoSelectFirstRow()
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
  return 'info'
}

function statusLabel(status) {
  if (status === 'migrated') return '已迁移'
  if (status === 'deleted') return '已删除'
  return '未迁移'
}

function blobColumnNames() {
  const view = activeView.value
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

function blobColumnName() {
  return blobColumnNames()[0] || ''
}

function getRowImageInfoId(row) {
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
    (a, b) => getRowKey(a) === getRowKey(b),
  )
}

function getRowKey(row) {
  const pk = activeView.value?.source_pk_column
  if (pk && row?.[pk] != null) return String(row[pk])
  return getRowImageInfoId(row) ?? JSON.stringify(row)
}

watch(tableRows, () => {
  if (selectedRow.value && !tableRows.value.some((row) => getRowKey(row) === getRowKey(selectedRow.value))) {
    selectedRow.value = null
  }
  setupTableViewport()
})

watch(activeViewId, (id, oldId) => {
  if (!browseReady.value || id === oldId) return
  unbindTableScroll()
  selectedRow.value = null
  if (!id) {
    columns.value = []
    tableRows.value = []
    total.value = 0
    hasMore.value = false
    return
  }
  void loadRows({ append: false })
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

watch(rightTab, (tab) => {
  if (tab === 'browse') {
    setupTableViewport()
  }
})

onMounted(async () => {
  window.addEventListener('resize', syncTableHeight)

  browseReady.value = false
  await loadViews()

  const routeViewId = Number(route.query.viewId)
  if (routeViewId && !Number.isNaN(routeViewId) && views.value.some((v) => v.id === routeViewId)) {
    activeViewId.value = routeViewId
  }

  browseReady.value = true
  if (activeViewId.value) {
    await loadRows({ append: false })
  }
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
            <el-button link type="primary" :loading="loadingViews" @click="loadViews">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </div>
          <div class="catalog-tree-wrap">
            <el-tree
              :key="`catalog-${viewsVersion}`"
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
                    v-if="findSavedViewForCatalogNode(data)"
                    size="small"
                    type="success"
                    effect="plain"
                    class="catalog-saved-tag"
                  >
                    已保存
                  </el-tag>
                </span>
              </template>
            </el-tree>
          </div>

          <div v-if="selectedCatalogObject" class="catalog-selection">
            <div class="catalog-selection-title">
              已选对象
              <el-tag v-if="savedViewForSelection" size="small" type="success" effect="plain">已保存</el-tag>
            </div>
            <div>{{ selectedCatalogObject.database }}.{{ selectedCatalogObject.label }}</div>
            <div class="field-hint">
              {{ selectedCatalogObject.objectType === 'view' ? '数据库视图' : '表' }}
              <template v-if="selectedCatalogObject.blobColumns?.length">
                · {{ selectedCatalogObject.blobColumns.map((c) => c.column).join(', ') }}
              </template>
              <template v-if="savedViewForSelection?.row_count != null">
                · {{ savedViewForSelection.row_count }} 行
              </template>
            </div>
            <div class="catalog-actions">
              <el-button
                v-if="!savedViewForSelection"
                size="small"
                type="primary"
                plain
                @click="openCreateViewDialog"
              >
                创建配置
              </el-button>
              <el-button
                v-if="savedViewForSelection"
                size="small"
                type="primary"
                plain
                @click="activeViewId = savedViewForSelection.id; rightTab = 'browse'"
              >
                打开
              </el-button>
              <el-button v-if="savedViewForSelection" size="small" plain @click="refreshActiveView">
                刷新
              </el-button>
              <el-button v-if="savedViewForSelection" size="small" type="danger" plain @click="removeView(savedViewForSelection)">
                删除配置
              </el-button>
              <el-button size="small" plain @click="rightTab = 'sql'">SQL 查询</el-button>
              <el-button size="small" link type="primary" @click="goMigrateWithCatalog">
                去迁移页
              </el-button>
            </div>
          </div>
        </aside>

        <main class="data-panel">
          <el-tabs v-model="rightTab" class="right-tabs">
            <el-tab-pane label="表数据" name="browse">
              <div v-if="activeView" class="browse-pane">
                <div class="data-head">
                  <div>
                    <h3>{{ activeView.source_table }}</h3>
                    <p class="field-hint">
                      {{ activeView.db_label || activeView.db_alias }} /
                      {{ activeView.source_table }} · PK {{ activeView.source_pk_column }} ·
                      BLOB → {{ blobColumnNames().join(', ') }}
                      <span v-if="activeView.where_clause"> · WHERE {{ activeView.where_clause }}</span>
                    </p>
                  </div>
                  <div class="data-head-actions">
                    <span class="row-count">已加载 {{ tableRows.length }} / {{ total }}</span>
                    <el-button :loading="loadingRows" @click="refreshActiveView">刷新</el-button>
                  </div>
                </div>

                <div class="table-panel">
                  <div class="table-main">
                    <div
                      ref="tableWrapRef"
                      v-loading="loadingRows && !tableRows.length"
                      class="table-viewport"
                    >
                      <el-table
                        v-if="columns.length"
                        ref="tableRef"
                        :data="tableRows"
                        :height="tableHeight"
                        size="small"
                        border
                        stripe
                        highlight-current-row
                        :row-key="getRowKey"
                        class="data-table compact-table"
                        empty-text="无数据"
                        @row-click="onTableRowClick"
                      >
                        <el-table-column
                          v-for="col in columns"
                          :key="col.name"
                          :prop="col.name"
                          :label="col.is_path_substitute ? `${col.name}（路径）` : col.name"
                          :min-width="col.is_path_substitute ? 200 : 100"
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
                      <el-empty v-else-if="!loadingRows" description="无数据" />
                    </div>
                    <div v-if="loadingMore" class="load-more-hint">加载更多…</div>
                    <div v-else-if="tableRows.length && !hasMore" class="load-more-hint muted">已全部加载</div>
                  </div>

                  <div
                    ref="rowPreviewPanelRef"
                    class="row-preview-panel"
                    tabindex="0"
                    @keydown="onPreviewKeydown"
                    @wheel="onPreviewWheel"
                  >
                    <div class="row-preview-head">
                      <span>行预览</span>
                      <span v-if="selectedRowPreviewItems.length" class="row-preview-count">
                        {{ selectedRowPreviewItems.length }} 张
                      </span>
                      <span
                        v-if="previewableTableRows.length > 1 && selectedPreviewRowIndex >= 0"
                        class="row-preview-count"
                      >
                        第 {{ selectedPreviewRowIndex + 1 }} / {{ previewableTableRows.length }} 行
                      </span>
                      <span v-if="previewableTableRows.length > 1" class="row-preview-hint">
                        聚焦后 ↑↓ 或滚轮切换行
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
                          :image-id="item.cell.image_info_id"
                          :image-path="item.cell.path"
                          :size="112"
                        />
                        <div class="row-preview-path" :title="item.title">{{ item.title }}</div>
                      </div>
                    </div>
                    <div v-else class="row-preview-empty">点击表格行，在下方并排预览该行已迁移的图片</div>
                  </div>
                </div>
              </div>
              <el-empty v-else description="请在左侧目录选择对象，或打开已保存的配置" />
            </el-tab-pane>

            <el-tab-pane label="SQL 查询" name="sql">
              <div class="sql-context-bar">
                当前数据源：<code>{{ browseContext.label }}</code>
                <span v-if="browseContext.database" class="field-hint inline-hint">
                  （库 {{ browseContext.database }}）
                </span>
              </div>
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
              <el-table
                v-if="sqlTableData.length"
                :data="sqlTableData"
                size="small"
                border
                stripe
                max-height="420"
                class="sql-result-table"
              >
                <el-table-column
                  v-for="col in sqlResult.columns"
                  :key="col"
                  :prop="col"
                  :label="col"
                  min-width="120"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">
                    {{ formatCellValue(row[col]) }}
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-else-if="!sqlExecuting" description="执行 SELECT 后在此显示结果" />
            </el-tab-pane>
          </el-tabs>
        </main>
      </div>
    </div>

    <el-dialog v-model="createViewDialogVisible" title="从目录创建配置" width="480px">
      <el-form label-width="100px">
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
        <el-form-item label="WHERE">
          <el-input v-model="createViewForm.whereClause" placeholder="不含 WHERE 关键字" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createViewDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createViewSaving" @click="submitCreateView">创建</el-button>
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

.catalog-saved-tag {
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

.sql-context-bar {
  font-size: 13px;
  margin-bottom: 8px;
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

.sql-result-table {
  width: 100%;
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
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}

.data-table {
  width: 100%;
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

.data-table :deep(.el-scrollbar__bar.is-vertical) {
  width: 10px;
  right: 0;
}

.data-table :deep(.el-scrollbar__bar.is-horizontal) {
  height: 10px;
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
