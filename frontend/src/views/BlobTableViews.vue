<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Refresh, View } from '@element-plus/icons-vue'
import ImageGalleryPanel from '@/components/ImageGalleryPanel.vue'
import {
  deleteBlobTableViewApi,
  fetchBlobTableViewRowsApi,
  listBlobTableViewsApi,
} from '@/api/images'
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
    ElMessage.error(err.message || '加载视图列表失败')
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
    await ElMessageBox.confirm(`确定删除视图「${row.name}」？`, '确认', { type: 'warning' })
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

function blobColumnName() {
  return activeView.value?.blob_column || ''
}

function getRowImageInfoId(row) {
  const cell = pathCell(row, blobColumnName())
  return cell?.image_info_id ?? null
}

function syncTableCurrentRow(row) {
  highlightAndScrollTableRow(
    tableRef,
    row,
    (a, b) => getRowImageInfoId(a) === getRowImageInfoId(b),
  )
}

function buildGalleryItems() {
  const blobCol = blobColumnName()
  if (!blobCol) return []
  return tableRows.value
    .map((row) => {
      const cell = pathCell(row, blobCol)
      if (!cell?.image_info_id || cell.status !== 'migrated') return null
      return {
        id: cell.image_info_id,
        path: cell.path,
        title: cell.path || cell.display,
      }
    })
    .filter(Boolean)
}

function openPreview(pathCellValue, row) {
  if (!pathCellValue?.image_info_id) return
  galleryItems.value = buildGalleryItems()
  const index = galleryItems.value.findIndex((item) => item.id === pathCellValue.image_info_id)
  if (index < 0) return
  galleryIndex.value = index
  syncTableCurrentRow(row ?? findRowByImageId(pathCellValue.image_info_id))
}

function findRowByImageId(imageId) {
  return tableRows.value.find((row) => getRowImageInfoId(row) === imageId)
}

function onTableRowClick(row, _column, event) {
  if (event?.target?.closest?.('button, a, .el-button')) return
  const cell = pathCell(row, blobColumnName())
  if (cell?.image_info_id && cell.status === 'migrated') {
    openPreview(cell, row)
  }
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
  if (prevId == null) return
  const nextIndex = galleryItems.value.findIndex((item) => item.id === prevId)
  galleryIndex.value = nextIndex
})

watch(activeViewId, () => {
  unbindTableScroll()
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
    }
  },
  { immediate: true },
)

onMounted(async () => {
  window.addEventListener('resize', syncTableHeight)

  await loadViews()
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
      <h2 class="page-title">BLOB 表视图</h2>
      <p class="page-desc">
        读取远程旧表数据，BLOB 列显示为本系统路径（来自 BLOB 迁移映射）。不创建物理表，仅保存查询配置。
      </p>

      <div class="layout">
        <aside class="view-list-panel">
          <div class="panel-head">
            <span>已保存视图</span>
            <el-button link type="primary" :loading="loadingViews" @click="loadViews">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </div>
          <el-skeleton v-if="loadingViews && !views.length" :rows="4" animated />
          <el-empty v-else-if="!views.length" description="暂无视图，可在 BLOB 迁移页保存" />
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
          <template v-if="activeView">
            <div class="data-head">
              <div>
                <h3>{{ activeView.name }}</h3>
                <p class="field-hint">
                  {{ activeView.db_label || activeView.db_alias }} /
                  {{ activeView.source_table }} · PK {{ activeView.source_pk_column }} ·
                  BLOB → 路径列 {{ activeView.blob_column }}
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
          </template>
          <el-empty v-else description="请选择左侧视图" />
        </main>
      </div>
    </div>
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
  grid-template-columns: 280px 1fr;
  gap: 16px;
  flex: 1;
  min-height: 0;
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
  min-height: 0;
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
