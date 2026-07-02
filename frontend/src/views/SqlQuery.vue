<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleCheck,
  Delete,
  Document,
  Download,
  VideoPlay,
} from '@element-plus/icons-vue'
import ImagePreview from '@/components/ImagePreview.vue'
import SqlEditor from '@/components/SqlEditor.vue'
import { fetchImageBlob } from '@/api/images'
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

const SQL_DRAFT_KEY = 'image_db_sql_draft'

const sqlText = ref('')
const editorRef = ref()
const executing = ref(false)
const validating = ref(false)
const templates = ref([])
const selectedTemplateId = ref('')
const lastError = ref('')

const result = ref(null)

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewSrc = ref('')
const previewTitle = ref('')
let previewObjectUrl = ''

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

function revokePreviewUrl() {
  if (previewObjectUrl) {
    URL.revokeObjectURL(previewObjectUrl)
    previewObjectUrl = ''
  }
  previewSrc.value = ''
}

async function openOriginalPreview(row) {
  const path = getPathFromRow(row)
  if (!path) return

  previewTitle.value = path
  previewVisible.value = true
  previewLoading.value = true
  revokePreviewUrl()

  try {
    const blob = await fetchImageBlob(path, { id: getIdFromRow(row), thumb: false })
    previewObjectUrl = URL.createObjectURL(blob)
    previewSrc.value = previewObjectUrl
  } catch (err) {
    previewVisible.value = false
    ElMessage.error(err.message || '原图加载失败')
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  previewVisible.value = false
  revokePreviewUrl()
}

onMounted(() => {
  loadDraft()
  loadTemplates()
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
            结果含 <code>image_path</code> 时将显示缩略图，点击可预览原图。
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
        v-if="hasResult && !pathColumn"
        type="info"
        show-icon
        :closable="false"
        class="preview-hint"
        title="未识别到图片路径列。请在 SELECT 中包含 image_path（或 save_path），查询结果即可显示缩略图并点击预览原图。"
      />

      <el-table
        :data="tableData"
        stripe
        border
        max-height="520"
        style="width: 100%"
        empty-text="查询成功，但无数据行"
      >
        <el-table-column
          v-if="pathColumn"
          label="预览"
          width="96"
          fixed="left"
          align="center"
        >
          <template #default="{ row }">
            <ImagePreview
              v-if="getPathFromRow(row)"
              :image-id="getIdFromRow(row)"
              :image-path="getPathFromRow(row)"
              :size="64"
              clickable
              @click="openOriginalPreview(row)"
            />
            <span v-else class="no-preview">—</span>
          </template>
        </el-table-column>

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
      </el-table>
    </div>

    <el-dialog
      v-model="previewVisible"
      :title="previewTitle"
      width="80%"
      top="5vh"
      destroy-on-close
      @closed="closePreview"
    >
      <div v-loading="previewLoading" class="preview-dialog-body">
        <img v-if="previewSrc" :src="previewSrc" alt="原图预览" class="preview-image" />
      </div>
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

.preview-dialog-body {
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-image {
  max-width: 100%;
  max-height: 75vh;
  object-fit: contain;
}
</style>
