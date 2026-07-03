<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleCheck,
  Delete,
  Document,
  Download,
  Edit,
  VideoPlay,
  View,
} from '@element-plus/icons-vue'
import ImageGalleryPanel from '@/components/ImageGalleryPanel.vue'
import SqlEditor from '@/components/SqlEditor.vue'
import {
  deleteImageApi,
  downloadImageFile,
  listCategoriesApi,
  updateImageApi,
} from '@/api/images'
import {
  executeSqlApi,
  findPathColumn,
  formatCellValue,
  listSqlTemplatesApi,
  rowsToRecords,
  saveSqlTemplateApi,
  validateSqlApi,
} from '@/api/sql'
import { exportSqlResultToExcel } from '@/utils/exportExcel'
import { useAuthStore } from '@/stores/auth'
import { highlightAndScrollTableRow } from '@/utils/tableScroll'

const auth = useAuthStore()

const SQL_DRAFT_KEY = 'image_db_sql_draft'

const sqlText = ref('')
const editorRef = ref()
const executing = ref(false)
const validating = ref(false)
const templates = ref([])
const selectedTemplateId = ref('')
const lastError = ref('')

const result = ref(null)

const resultTableRef = ref(null)
const galleryItems = ref([])
const galleryIndex = ref(-1)

const categories = ref([])
const editVisible = ref(false)
const editSaving = ref(false)
const editForm = reactive({
  id: null,
  image_name: '',
  category_id: null,
  tags: '',
})

const IMAGE_NAME_FIELDS = ['image_name', 'name', 'filename']
const UPLOAD_USER_FIELDS = ['upload_user', 'user', 'username']
const SUFFIX_FIELDS = ['file_suffix', 'suffix']
const CATEGORY_FIELDS = ['category_id']
const TAGS_FIELDS = ['tags']

const pathColumn = computed(() => {
  if (!result.value) return null
  return findPathColumn(result.value.columns, result.value.rows)
})

const tableData = computed(() => {
  if (!result.value) return []
  return rowsToRecords(result.value.columns, result.value.rows)
})

const idColumn = computed(() => {
  if (!result.value?.columns) return null
  const lower = result.value.columns.map((c) => String(c).toLowerCase())
  const idx = lower.indexOf('id')
  return idx >= 0 ? result.value.columns[idx] : null
})

const hasResult = computed(() => Boolean(result.value?.columns?.length))

const showImageActions = computed(() => Boolean(pathColumn.value && idColumn.value))

function pickRowField(row, candidates) {
  for (const key of candidates) {
    if (row[key] != null && row[key] !== '') return row[key]
  }
  const lowerMap = {}
  Object.keys(row).forEach((key) => {
    lowerMap[key.toLowerCase()] = key
  })
  for (const key of candidates) {
    const actual = lowerMap[key.toLowerCase()]
    if (actual && row[actual] != null && row[actual] !== '') return row[actual]
  }
  return ''
}

function canOperateImageRow(row) {
  return getIdFromRow(row) != null && Boolean(getPathFromRow(row))
}

function canModifyImageRow(row) {
  if (!canOperateImageRow(row)) return false
  if (auth.isAdmin) return true
  const uploader = String(pickRowField(row, UPLOAD_USER_FIELDS) || '').trim()
  return uploader && uploader === auth.username
}

function buildDeleteConfirmMessage(row) {
  const name = pickRowField(row, IMAGE_NAME_FIELDS) || `图片 #${getIdFromRow(row)}`
  return [
    `确定永久删除图片「${name}」吗？`,
    '',
    '• 将立即删除 upload/ 中的文件、image_info 记录及 BLOB 迁移映射。',
    '• 此操作不可恢复；若来自 BLOB 迁移，需从源库重新迁移。',
  ].join('\n')
}

async function loadCategories() {
  try {
    const res = await listCategoriesApi()
    categories.value = res.data || []
  } catch {
    categories.value = []
  }
}

function loadDraft() {
  const draft = localStorage.getItem(SQL_DRAFT_KEY)
  if (draft) {
    sqlText.value = draft
  } else {
    sqlText.value = `SELECT id, image_name, image_path, upload_time, upload_user
FROM image_info
WHERE is_delete = 0
ORDER BY upload_time DESC
LIMIT 20`
  }
}

function persistDraft() {
  localStorage.setItem(SQL_DRAFT_KEY, sqlText.value)
}

async function loadTemplates() {
  try {
    const res = await listSqlTemplatesApi()
    templates.value = res.data || []
  } catch {
    templates.value = []
  }
}

function applyTemplate(templateId) {
  const tpl = templates.value.find((t) => t.id === templateId)
  if (tpl) {
    sqlText.value = tpl.sql
    persistDraft()
  }
}

function clearEditor() {
  sqlText.value = ''
  result.value = null
  lastError.value = ''
  selectedTemplateId.value = ''
  localStorage.removeItem(SQL_DRAFT_KEY)
  editorRef.value?.focus()
}

async function handleValidate() {
  const sql = sqlText.value.trim()
  if (!sql) {
    ElMessage.warning('请输入 SQL 语句')
    return
  }

  validating.value = true
  lastError.value = ''
  try {
    await validateSqlApi(sql)
    ElMessage.success('SQL 校验通过')
  } catch (err) {
    lastError.value = err.message || 'SQL 校验失败'
  } finally {
    validating.value = false
  }
}

async function handleExecute() {
  const sql = sqlText.value.trim()
  if (!sql) {
    ElMessage.warning('请输入 SQL 语句')
    return
  }

  executing.value = true
  lastError.value = ''
  result.value = null
  galleryIndex.value = -1
  persistDraft()

  try {
    const res = await executeSqlApi(sql)
    result.value = res.data
    ElMessage.success(res.message || '查询成功')
  } catch (err) {
    lastError.value = err.message || '查询失败'
  } finally {
    executing.value = false
  }
}

async function handleSaveTemplate() {
  const sql = sqlText.value.trim()
  if (!sql) {
    ElMessage.warning('请先输入 SQL 再保存模板')
    return
  }

  try {
    const { value } = await ElMessageBox.prompt('请输入模板名称', '保存 SQL 模板', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputPattern: /\S+/,
      inputErrorMessage: '模板名称不能为空',
    })

    const res = await saveSqlTemplateApi(value.trim(), sql)
    ElMessage.success(res.message || '模板已保存')
    await loadTemplates()
    selectedTemplateId.value = res.data?.id || ''
  } catch (err) {
    if (err !== 'cancel' && err?.message) {
      // error already shown by interceptor
    }
  }
}

function handleExport() {
  if (!hasResult.value) {
    ElMessage.warning('暂无查询结果可导出')
    return
  }
  const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
  exportSqlResultToExcel(result.value.columns, result.value.rows, `sql_result_${ts}.xlsx`)
  ElMessage.success('Excel 已导出')
}

function getPathFromRow(row) {
  if (!pathColumn.value) return ''
  return row[pathColumn.value] || ''
}

function getIdFromRow(row) {
  if (!idColumn.value) return null
  const val = row[idColumn.value]
  if (val == null || val === '') return null
  const num = Number(val)
  return Number.isFinite(num) ? num : null
}

function isPathColumn(col) {
  return pathColumn.value && col === pathColumn.value
}

function buildGalleryItems() {
  return tableData.value
    .filter((row) => canOperateImageRow(row))
    .map((row) => ({
      id: getIdFromRow(row),
      path: getPathFromRow(row),
      title: pickRowField(row, IMAGE_NAME_FIELDS) || getPathFromRow(row),
    }))
}

function syncTableCurrentRow(row) {
  highlightAndScrollTableRow(
    resultTableRef,
    row,
    (a, b) => getIdFromRow(a) === getIdFromRow(b),
  )
}

function openOriginalPreview(row) {
  if (!canOperateImageRow(row)) return
  galleryItems.value = buildGalleryItems()
  const id = getIdFromRow(row)
  const index = galleryItems.value.findIndex((item) => item.id === id)
  if (index < 0) return
  galleryIndex.value = index
  syncTableCurrentRow(row)
}

function onResultRowClick(row, _column, event) {
  if (event?.target?.closest?.('button, a, .el-button')) return
  if (canOperateImageRow(row)) {
    openOriginalPreview(row)
  }
}

watch(galleryIndex, (index) => {
  if (index < 0) {
    syncTableCurrentRow(null)
    return
  }
  const item = galleryItems.value[index]
  if (!item) return
  const row = tableData.value.find((entry) => getIdFromRow(entry) === item.id)
  syncTableCurrentRow(row)
})

watch(tableData, () => {
  const prevId = galleryItems.value[galleryIndex.value]?.id
  galleryItems.value = buildGalleryItems()
  if (prevId == null) return
  const nextIndex = galleryItems.value.findIndex((item) => item.id === prevId)
  galleryIndex.value = nextIndex
})

async function handleDownload(row) {
  if (!canOperateImageRow(row)) return
  try {
    const id = getIdFromRow(row)
    const path = getPathFromRow(row)
    const suffix = pickRowField(row, SUFFIX_FIELDS) || 'jpg'
    const filename = pickRowField(row, IMAGE_NAME_FIELDS) || `image_${id}.${suffix}`
    await downloadImageFile({ id, path, filename })
    ElMessage.success('下载已开始')
  } catch (err) {
    ElMessage.error(err.message || '下载失败')
  }
}

function openEdit(row) {
  if (!canModifyImageRow(row)) return
  editForm.id = getIdFromRow(row)
  editForm.image_name = pickRowField(row, IMAGE_NAME_FIELDS)
  const categoryRaw = pickRowField(row, CATEGORY_FIELDS)
  editForm.category_id = categoryRaw != null && categoryRaw !== '' ? Number(categoryRaw) : null
  editForm.tags = pickRowField(row, TAGS_FIELDS) || ''
  editVisible.value = true
}

async function submitEdit() {
  if (!editForm.image_name?.trim()) {
    ElMessage.warning('图片名称不能为空')
    return
  }
  if (!editForm.category_id) {
    ElMessage.warning('请选择分类')
    return
  }
  editSaving.value = true
  try {
    await updateImageApi(editForm.id, {
      image_name: editForm.image_name.trim(),
      category_id: editForm.category_id,
      tags: editForm.tags.trim(),
    })
    ElMessage.success('更新成功')
    editVisible.value = false
    await refreshResult()
  } finally {
    editSaving.value = false
  }
}

async function handleDelete(row) {
  if (!canModifyImageRow(row)) return
  await ElMessageBox.confirm(
    buildDeleteConfirmMessage(row).replace(/\n/g, '<br/>'),
    '确认删除',
    {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      dangerouslyUseHTMLString: true,
    },
  )
  const res = await deleteImageApi(getIdFromRow(row))
  ElMessage.success(res.data?.notice || res.message || '图片已永久删除')
  await refreshResult()
}

async function refreshResult() {
  const sql = sqlText.value.trim()
  if (!sql || !result.value) return
  try {
    const res = await executeSqlApi(sql)
    result.value = res.data
  } catch (err) {
    ElMessage.error(err.message || '刷新结果失败')
  }
}

onMounted(() => {
  loadDraft()
  loadTemplates()
  loadCategories()
})
</script>

<template>
  <div class="sql-page">
    <div class="page-card editor-panel">
      <div class="panel-header">
        <div>
          <h2 class="page-title">SQL 查询面板</h2>
          <p class="page-desc">
            仅支持 <code>SELECT</code> 查询。禁止 DROP / DELETE / UPDATE 等危险语句。
            快捷键 <kbd>Ctrl</kbd> + <kbd>Enter</kbd> 执行。
            结果含 <code>id</code> 与 <code>image_path</code> 时，右侧预览框可浏览图片并同步选中行；预览时可继续下载、编辑、删除。
          </p>
        </div>
        <el-select
          v-model="selectedTemplateId"
          placeholder="常用 SQL 模板"
          clearable
          filterable
          class="template-select"
          @change="applyTemplate"
        >
          <el-option
            v-for="tpl in templates"
            :key="tpl.id"
            :label="tpl.name"
            :value="tpl.id"
          >
            <span>{{ tpl.name }}</span>
            <el-tag v-if="tpl.builtin" size="small" type="info" class="tpl-tag">内置</el-tag>
          </el-option>
        </el-select>
      </div>

      <SqlEditor
        ref="editorRef"
        v-model="sqlText"
        min-height="240px"
        @execute="handleExecute"
      />

      <div class="toolbar">
        <el-button type="primary" :icon="VideoPlay" :loading="executing" @click="handleExecute">
          执行查询
        </el-button>
        <el-button :icon="CircleCheck" :loading="validating" @click="handleValidate">
          校验 SQL
        </el-button>
        <el-button :icon="Document" @click="handleSaveTemplate">保存模板</el-button>
        <el-button :icon="Download" :disabled="!hasResult" @click="handleExport">
          导出 Excel
        </el-button>
        <el-button :icon="Delete" @click="clearEditor">清空</el-button>
      </div>

      <el-alert
        v-if="lastError"
        :title="lastError"
        type="error"
        show-icon
        closable
        class="error-alert"
        @close="lastError = ''"
      />
    </div>

    <div v-if="result" class="page-card result-panel">
      <div class="result-header">
        <h3 class="section-title">查询结果</h3>
        <div class="result-meta">
          <el-tag type="info">{{ result.row_count }} 行</el-tag>
          <el-tag type="success">{{ result.elapsed_ms }} ms</el-tag>
          <el-tag v-if="result.truncated" type="warning">结果已截断（超过行数上限）</el-tag>
          <el-tag v-if="pathColumn" type="primary">已识别路径列：{{ pathColumn }}</el-tag>
        </div>
      </div>

      <el-alert
        v-if="hasResult && pathColumn && !idColumn"
        type="info"
        show-icon
        :closable="false"
        class="preview-hint"
        title="已识别路径列，但未找到 id 列。请在 SELECT 中包含 id（image_info 主键），方可下载、编辑或删除。"
      />

      <el-alert
        v-if="hasResult && !pathColumn"
        type="info"
        show-icon
        :closable="false"
        class="preview-hint"
        title="未识别到图片路径列。请在 SELECT 中包含 image_path（或 save_path），点击行或路径列即可在右侧预览。"
      />

      <div class="result-with-preview">
        <div class="result-table-area">
      <el-table
        ref="resultTableRef"
        :data="tableData"
        stripe
        border
        highlight-current-row
        :row-key="(row) => getIdFromRow(row) ?? getPathFromRow(row)"
        max-height="520"
        style="width: 100%"
        empty-text="查询成功，但无数据行"
        @row-click="onResultRowClick"
      >
        <el-table-column
          v-for="col in result.columns"
          :key="col"
          :prop="col"
          :label="col"
          :min-width="isPathColumn(col) ? 220 : 120"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <span
              v-if="isPathColumn(col) && getPathFromRow(row)"
              class="path-text path-link"
              :title="`${getPathFromRow(row)}（点击预览原图）`"
              @click="openOriginalPreview(row)"
            >
              {{ getPathFromRow(row) }}
            </span>
            <span v-else>{{ formatCellValue(row[col]) }}</span>
          </template>
        </el-table-column>

        <el-table-column
          v-if="showImageActions"
          label="操作"
          width="220"
          fixed="right"
          align="center"
        >
          <template #default="{ row }">
            <template v-if="canOperateImageRow(row)">
              <el-button link type="primary" :icon="View" @click="openOriginalPreview(row)">
                预览
              </el-button>
              <el-button link type="primary" :icon="Download" @click="handleDownload(row)">
                下载
              </el-button>
              <el-button
                v-if="canModifyImageRow(row)"
                link
                type="primary"
                :icon="Edit"
                @click="openEdit(row)"
              >
                编辑
              </el-button>
              <el-button
                v-if="canModifyImageRow(row)"
                link
                type="danger"
                @click="handleDelete(row)"
              >
                删除
              </el-button>
            </template>
            <span v-else class="no-preview">—</span>
          </template>
        </el-table-column>
      </el-table>
        </div>

        <ImageGalleryPanel
          v-if="pathColumn"
          v-model:current-index="galleryIndex"
          :items="galleryItems"
          class="result-preview-pane"
        />
      </div>
    </div>

    <el-dialog
      v-model="editVisible"
      title="编辑图片信息"
      width="480px"
      destroy-on-close
    >
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="editForm.image_name" maxlength="255" />
        </el-form-item>
        <el-form-item label="分类" required>
          <el-select v-model="editForm.category_id" placeholder="请选择分类" style="width: 100%">
            <el-option
              v-for="cat in categories"
              :key="cat.id"
              :label="cat.category_name"
              :value="cat.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="editForm.tags" maxlength="500" placeholder="逗号分隔" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.sql-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.page-desc {
  margin: 4px 0 0;
  color: #606266;
  line-height: 1.6;
  font-size: 14px;
}

.page-desc code {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
}

.page-desc kbd {
  background: #eee;
  border: 1px solid #ccc;
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 12px;
}

.template-select {
  width: 240px;
  flex-shrink: 0;
}

.tpl-tag {
  margin-left: 8px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}

.error-alert {
  margin-top: 12px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.section-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.result-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.preview-hint {
  margin-bottom: 12px;
}

.result-with-preview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 16px;
  align-items: start;
}

.result-table-area {
  min-width: 0;
}

.result-preview-pane {
  position: sticky;
  top: 12px;
  max-height: 520px;
}

@media (max-width: 1100px) {
  .result-with-preview {
    grid-template-columns: 1fr;
  }

  .result-preview-pane {
    position: static;
    max-height: 320px;
  }
}

.no-preview {
  color: #c0c4cc;
}

.path-text {
  font-family: Consolas, monospace;
  font-size: 12px;
  color: #606266;
  word-break: break-all;
}

.path-link {
  color: #409eff;
  cursor: pointer;
}

.path-link:hover {
  text-decoration: underline;
}
</style>
