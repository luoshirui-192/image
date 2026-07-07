<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Refresh, VideoPlay, View } from '@element-plus/icons-vue'
import ImageGalleryPanel from '@/components/ImageGalleryPanel.vue'
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
const tableHeight = ref(520)
let tableScrollEl = null
let resizeObserver = null

const PAGE_SIZE = 80
const SCROLL_LOAD_DISTANCE = 120

const activeView = computed(() => views.value.find((v) => v.id === activeViewId.value) || null)

const galleryItems = ref([])
const galleryIndex = ref(-1)

const loadingCatalog = ref(false)
const selectedCatalogObject = ref(null)

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
    return
  }
  if (data.nodeType !== 'object') return
  selectedCatalogObject.value = data
  sqlText.value = `SELECT * FROM \`${data.label}\` LIMIT 80`
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
  createViewForm.name = `${obj.label} 浏览`
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
      name: createViewForm.name.trim() || `${obj.label} 浏览`,
      db_alias: conn.alias,
      database_name: obj.database,
      source_table: obj.label,
      source_object_type: obj.objectType || 'table',
      source_pk_column: createViewForm.sourcePkColumn.trim() || 'id',
      blob_columns: [...createViewForm.blobColumns],
      where_clause: createViewForm.whereClause.trim(),
    })
    ElMessage.success('浏览配置已创建')
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

function syncTableHeight() {
  const reservedTop = 56 + 16 + 16 + 20 + 12 + 72 + 28
  const fallbackHeight = Math.max(560, window.innerHeight - reservedTop)

  if (tableWrapRef.value) {
    const fromContainer = Math.floor(tableWrapRef.value.clientHeight)
    if (fromContainer > 240) {
      tableHeight.value = fromContainer
      return
    }
  }
  tableHeight.value = fallbackHeight
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
    if (!activeViewId.value && views.value.length) {
      activeViewId.value = views.value[0].id
    }
    if (activeViewId.value && !views.value.some((v) => v.id === activeViewId.value)) {
      activeViewId.value = views.value[0]?.id ?? null
    }
  } catch (err) {
    views.value = []
    ElMessage.error(err.message || '加载浏览配置失败')
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
    galleryIndex.value = -1
    return
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
    const res = await fetchBlobTableViewRowsApi(activeViewId.value, {
      offset: append ? offset.value : 0,
      limit: PAGE_SIZE,
    })
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
      autoSelectFirstPreview()
    }
  } catch (err) {
    if (!append) {
      columns.value = []
      tableRows.value = []
    }
    ElMessage.error(err.message || '加载数据失败')
  } finally {
    loadingRows.value = false
    loadingMore.value = false
    setupTableViewport()
  }
}

function selectView(id) {
  if (activeViewId.value === id) return
  activeViewId.value = id
}

async function refreshActiveView() {
  await loadRows({ append: false })
}

async function loadMore() {
  await loadRows({ append: true })
}

async function removeView(row) {
  try {
    await ElMessageBox.confirm(`确定删除浏览配置「${row.name}」？`, '确认', { type: 'warning' })
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
    (a, b) => getRowImageInfoId(a) === getRowImageInfoId(b),
  )
}

function buildGalleryItems() {
  const cols = blobColumnNames()
  if (!cols.length) return []
  const items = []
  for (const row of tableRows.value) {
    for (const col of cols) {
      const cell = pathCell(row, col)
      if (!cell?.image_info_id || cell.status !== 'migrated') continue
      items.push({
        id: cell.image_info_id,
        path: cell.path,
        title: cols.length > 1 ? `${col}: ${cell.path || cell.display}` : (cell.path || cell.display),
        column: col,
      })
    }
  }
  return items
}

function autoSelectFirstPreview() {
  const items = buildGalleryItems()
  galleryItems.value = items
  if (!items.length) {
    galleryIndex.value = -1
    return
  }
  if (galleryIndex.value < 0 || !items[galleryIndex.value]) {
    galleryIndex.value = 0
    syncTableCurrentRow(findRowByImageId(items[0].id))
  }
}

function openRowPreview(row, preferredColumn = null) {
  const items = buildGalleryItems()
  if (!items.length) return
  galleryItems.value = items
  let targetId = null
  if (preferredColumn) {
    const cell = pathCell(row, preferredColumn)
    targetId = cell?.image_info_id ?? null
  }
  if (!targetId) {
    for (const col of blobColumnNames()) {
      const cell = pathCell(row, col)
      if (cell?.image_info_id && cell.status === 'migrated') {
        targetId = cell.image_info_id
        break
      }
    }
  }
  const index = targetId ? items.findIndex((item) => item.id === targetId) : -1
  galleryIndex.value = index >= 0 ? index : 0
  syncTableCurrentRow(row)
}

function openPreview(pathCellValue, row) {
  if (!pathCellValue?.image_info_id) return
  const col = blobColumnNames().find((name) => pathCell(row, name) === pathCellValue)
  openRowPreview(row, col || null)
}

function findRowByImageId(imageId) {
  return tableRows.value.find((row) => getRowImageInfoId(row) === imageId)
}

function onTableRowClick(row, _column, event) {
  if (event?.target?.closest?.('button, a, .el-button')) return
  openRowPreview(row)
}

watch(galleryIndex, (index) => {
  if (index < 0) {
    syncTableCurrentRow(null)
    return
  }
  const item = galleryItems.value[index]
  if (!item) return
  syncTableCurrentRow(findRowByImageId(item.id))
})

watch(tableRows, () => {
  const prevId = galleryItems.value[galleryIndex.value]?.id
  galleryItems.value = buildGalleryItems()
  if (!galleryItems.value.length) {
    galleryIndex.value = -1
    return
  }
  if (prevId == null) {
    autoSelectFirstPreview()
    return
  }
  const nextIndex = galleryItems.value.findIndex((item) => item.id === prevId)
  galleryIndex.value = nextIndex >= 0 ? nextIndex : 0
})

watch(activeViewId, () => {
  unbindTableScroll()
  galleryIndex.value = -1
  loadRows({ append: false })
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

watch(tableRows, () => {
  setupTableViewport()
})

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

onMounted(async () => {
  window.addEventListener('resize', syncTableHeight)

  await Promise.all([loadViews()])
  await nextTick()
  if (route.query.viewId) {
    const id = Number(route.query.viewId)
    if (id && !Number.isNaN(id)) {
      activeViewId.value = id
    }
  }
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
      <h2 class="page-title">BLOB 数据浏览</h2>
      <p class="page-desc">
        左侧按连接与数据库浏览表、数据库视图；支持保存浏览配置、多 BLOB 并排预览，以及在同一页面执行 SQL 查询。
      </p>

      <div class="layout">
        <aside class="view-list-panel">
          <div class="panel-head">
            <span>数据库目录</span>
          </div>
          <el-tree
            lazy
            :load="loadCatalogTree"
            node-key="id"
            :props="{ label: 'label', isLeaf: 'leaf' }"
            highlight-current
            class="catalog-tree"
            @node-click="onCatalogNodeClick"
          >
            <template #default="{ data }">
              <span class="catalog-node">{{ catalogNodeLabel(data) }}</span>
            </template>
          </el-tree>

          <div v-if="selectedCatalogObject" class="catalog-selection">
            <div class="catalog-selection-title">已选对象</div>
            <div>{{ selectedCatalogObject.database }}.{{ selectedCatalogObject.label }}</div>
            <div class="field-hint">
              {{ selectedCatalogObject.objectType === 'view' ? '数据库视图' : '表' }}
            </div>
            <div class="catalog-actions">
              <el-button size="small" type="primary" plain @click="openCreateViewDialog">
                创建浏览配置
              </el-button>
              <el-button size="small" plain @click="rightTab = 'sql'">SQL 查询</el-button>
              <el-button size="small" link type="primary" @click="goMigrateWithCatalog">
                去迁移页
              </el-button>
            </div>
          </div>

          <div class="panel-head panel-head-spaced">
            <span>已保存浏览配置</span>
            <el-button link type="primary" :loading="loadingViews" @click="loadViews">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </div>
          <el-skeleton v-if="loadingViews && !views.length" :rows="4" animated />
          <el-empty v-else-if="!views.length" description="暂无浏览配置，可在 BLOB 迁移页保存" />
          <ul v-else class="view-list">
            <li
              v-for="item in views"
              :key="item.id"
              :class="['view-item', { active: item.id === activeViewId }]"
              @click="selectView(item.id)"
            >
              <div class="view-item-title">{{ item.name }}</div>
              <div class="view-item-meta">
                {{ item.db_label || item.db_alias }} · {{ item.source_table }}
              </div>
              <div class="view-item-stats">
                <span v-if="item.row_count != null">{{ item.row_count }} 行</span>
                <span v-else-if="item.stats_error" class="warn">无法统计</span>
              </div>
              <el-button
                link
                type="danger"
                class="view-item-delete"
                @click.stop="removeView(item)"
              >
                <el-icon><Delete /></el-icon>
              </el-button>
            </li>
          </ul>
          <el-button type="primary" plain class="goto-migrate" @click="router.push('/blob-migrate')">
            去 BLOB 迁移页新建
          </el-button>
        </aside>

        <main class="data-panel">
          <el-tabs v-model="rightTab" class="right-tabs">
            <el-tab-pane label="表浏览" name="browse">
              <div v-if="activeView" class="browse-pane">
                <div class="data-head">
                  <div>
                    <h3>{{ activeView.name }}</h3>
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
                        :row-key="(row) => getRowImageInfoId(row) ?? JSON.stringify(row)"
                        class="data-table"
                        empty-text="无数据"
                        @row-click="onTableRowClick"
                      >
                        <el-table-column
                          v-for="col in columns"
                          :key="col.name"
                          :prop="col.name"
                          :label="col.is_path_substitute ? `${col.name}（路径）` : col.name"
                          :min-width="col.is_path_substitute ? 220 : 120"
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

                  <ImageGalleryPanel
                    v-model:current-index="galleryIndex"
                    :items="galleryItems"
                    class="blob-preview-pane"
                  />
                </div>
              </div>
              <el-empty v-else description="请选择左侧浏览配置，或从目录创建" />
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

    <el-dialog v-model="createViewDialogVisible" title="从目录创建浏览配置" width="480px">
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

.catalog-tree {
  max-height: 240px;
  overflow: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 4px 0;
}

.catalog-node {
  font-size: 13px;
}

.catalog-selection {
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  font-size: 12px;
}

.catalog-selection-title {
  font-weight: 600;
  margin-bottom: 4px;
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
}

.browse-pane {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
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

.panel-head-spaced {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
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
}

.view-list {
  list-style: none;
  margin: 0;
  padding: 0;
  flex: 1;
  overflow: auto;
  min-height: 0;
}

.view-item {
  position: relative;
  padding: 10px 32px 10px 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
}

.view-item:hover {
  background: var(--el-fill-color-light);
}

.view-item.active {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}

.view-item-title {
  font-weight: 500;
  margin-bottom: 4px;
}

.view-item-meta,
.view-item-stats {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.view-item-stats .warn {
  color: var(--el-color-warning);
}

.view-item-delete {
  position: absolute;
  top: 8px;
  right: 4px;
}

.goto-migrate {
  width: 100%;
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
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 12px;
  overflow: hidden;
}

.table-main {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.blob-preview-pane {
  min-width: 260px;
  min-height: 280px;
  height: 100%;
  max-height: 100%;
}

.table-viewport {
  flex: 1;
  min-height: calc(100vh - var(--header-height) - 240px);
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}

.data-table {
  width: 100%;
}

.data-table :deep(.el-table__header-wrapper) {
  position: sticky;
  top: 0;
  z-index: 2;
}

.data-table :deep(.el-scrollbar__bar.is-vertical) {
  right: 0;
}

.path-cell {
  display: flex;
  align-items: center;
  gap: 6px;
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
