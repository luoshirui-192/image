<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Edit, RefreshRight, Search, View } from '@element-plus/icons-vue'
import ImagePreview from '@/components/ImagePreview.vue'
import {
  batchDeleteImagesApi,
  deleteImageApi,
  downloadImageFile,
  fetchDeletionPolicyApi,
  fetchImageBlob,
  formatDateTime,
  formatDeletionRemaining,
  formatFileSize,
  listCategoriesApi,
  listImagesApi,
  restoreImageApi,
  updateImageApi,
} from '@/api/images'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const loading = ref(false)
const batchDeleting = ref(false)
const tableRef = ref()
const selectedRows = ref([])
const categories = ref([])
const images = ref([])
const pagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
})

const filters = reactive({
  keyword: '',
  categoryId: null,
  tags: '',
  suffix: '',
  uploadUser: '',
  dateRange: null,
  includeDeleted: false,
  scope: auth.isAdmin ? 'all' : 'mine',
})

function canModifyRow(row) {
  return auth.isAdmin || row.upload_user === auth.username
}

const categoryMap = computed(() => {
  const map = {}
  categories.value.forEach((c) => {
    map[c.id] = c.category_name
  })
  return map
})

const selectedActiveCount = computed(() => selectedRows.value.filter((row) => !row.is_delete).length)
const canBatchDelete = computed(
  () => auth.isAdmin && selectedActiveCount.value > 0 && !batchDeleting.value,
)

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewSrc = ref('')
const previewTitle = ref('')
let previewObjectUrl = ''

const editVisible = ref(false)
const editSaving = ref(false)
const editForm = reactive({
  id: null,
  image_name: '',
  category_id: null,
  tags: '',
})

const deletionPolicy = ref({
  retention_days: 30,
  summary: '',
})

function buildDeleteConfirmMessage(row) {
  const days = deletionPolicy.value.retention_days || 30
  return [
    `确定删除图片「${row.image_name}」吗？`,
    '',
    `• 这是逻辑删除：列表中将不再显示，但数据库与磁盘文件会暂时保留 ${days} 天。`,
    `• 预计 ${days} 天后由系统自动永久删除（自删除时刻起算）。`,
    `• 保留期内可在本页开启「含已删」后点击「恢复」找回。`,
  ].join('\n')
}

function buildBatchDeleteConfirmMessage(count) {
  const days = deletionPolicy.value.retention_days || 30
  return [
    `确定批量删除选中的 ${count} 张图片吗？`,
    '',
    `• 这是逻辑删除：列表中将不再显示，但数据库与磁盘文件会暂时保留 ${days} 天。`,
    `• 预计 ${days} 天后由系统自动永久删除（自删除时刻起算）。`,
    `• 保留期内可在本页开启「含已删」后点击「恢复」找回。`,
  ].join('\n')
}

function buildDeleteSuccessMessage(data) {
  if (data?.notice) return data.notice
  const days = data?.deletion_info?.retention_days || deletionPolicy.value.retention_days || 30
  const purgeAt = data?.deletion_info?.purge_at
  if (purgeAt) {
    return `已逻辑删除，预计 ${purgeAt} 永久删除（保留 ${days} 天）。`
  }
  return `已逻辑删除，文件将在 ${days} 天后永久删除。`
}

function buildQueryParams() {
  const params = {
    page: pagination.page,
    page_size: pagination.pageSize,
  }
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim()
  if (filters.categoryId != null && filters.categoryId !== '') {
    params.category_id = filters.categoryId
  }
  if (filters.tags.trim()) params.tags = filters.tags.trim()
  if (filters.suffix.trim()) params.suffix = filters.suffix.trim()
  if (filters.uploadUser.trim()) params.upload_user = filters.uploadUser.trim()
  else if (!auth.isAdmin && filters.scope === 'mine') {
    params.upload_user = auth.username
  }
  if (filters.dateRange?.length === 2) {
    params.upload_time_from = filters.dateRange[0]
    params.upload_time_to = filters.dateRange[1]
  }
  if (filters.includeDeleted) {
    params.include_deleted = 1
  }
  return params
}

async function loadCategories() {
  try {
    const res = await listCategoriesApi()
    categories.value = res.data || []
  } catch {
    categories.value = []
  }
}

async function loadImages() {
  loading.value = true
  try {
    const res = await listImagesApi(buildQueryParams())
    const data = res.data
    images.value = data.results || []
    pagination.total = data.count || 0
    clearSelection()
  } catch {
    images.value = []
    pagination.total = 0
    clearSelection()
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  pagination.page = 1
  loadImages()
}

function resetFilters() {
  filters.keyword = ''
  filters.categoryId = null
  filters.tags = ''
  filters.suffix = ''
  filters.uploadUser = auth.isAdmin ? '' : auth.username
  filters.dateRange = null
  filters.includeDeleted = false
  filters.scope = auth.isAdmin ? 'all' : 'mine'
  pagination.page = 1
  loadImages()
}

function handleScopeChange() {
  if (filters.scope === 'mine') {
    filters.uploadUser = auth.username
  } else {
    filters.uploadUser = ''
  }
  pagination.page = 1
  loadImages()
}

function handlePageChange(page) {
  pagination.page = page
  loadImages()
}

function handleSizeChange(size) {
  pagination.pageSize = size
  pagination.page = 1
  loadImages()
}

function revokePreviewUrl() {
  if (previewObjectUrl) {
    URL.revokeObjectURL(previewObjectUrl)
    previewObjectUrl = ''
  }
  previewSrc.value = ''
}

async function openPreview(row) {
  previewTitle.value = row.image_name || `图片 #${row.id}`
  previewVisible.value = true
  previewLoading.value = true
  revokePreviewUrl()
  try {
    const blob = await fetchImageBlob(row.image_path, { id: row.id, thumb: false })
    previewObjectUrl = URL.createObjectURL(blob)
    previewSrc.value = previewObjectUrl
  } catch (err) {
    previewVisible.value = false
    ElMessage.error(err.message || '预览失败')
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  previewVisible.value = false
  revokePreviewUrl()
}

async function handleDownload(row) {
  try {
    const filename = row.image_name || `image_${row.id}.${row.file_suffix || 'jpg'}`
    await downloadImageFile({ id: row.id, path: row.image_path, filename })
    ElMessage.success('下载已开始')
  } catch (err) {
    ElMessage.error(err.message || '下载失败')
  }
}

function openEdit(row) {
  editForm.id = row.id
  editForm.image_name = row.image_name
  editForm.category_id = row.category_id || null
  editForm.tags = row.tags || ''
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
    loadImages()
  } finally {
    editSaving.value = false
  }
}

async function handleDelete(row) {
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
  const res = await deleteImageApi(row.id)
  ElMessage.success(buildDeleteSuccessMessage(res.data))
  if (images.value.length === 1 && pagination.page > 1) {
    pagination.page -= 1
  }
  loadImages()
}

function rowSelectable(row) {
  return !row.is_delete && canModifyRow(row)
}

function handleSelectionChange(rows) {
  selectedRows.value = rows
}

function clearSelection() {
  selectedRows.value = []
  tableRef.value?.clearSelection()
}

async function handleBatchDelete() {
  const targets = selectedRows.value.filter((row) => !row.is_delete)
  if (!targets.length) {
    ElMessage.warning('请先选择未删除的图片')
    return
  }

  await ElMessageBox.confirm(
    buildBatchDeleteConfirmMessage(targets.length).replace(/\n/g, '<br/>'),
    '确认批量删除',
    {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      dangerouslyUseHTMLString: true,
    },
  )

  batchDeleting.value = true
  try {
    const res = await batchDeleteImagesApi(targets.map((row) => row.id))
    const summary = res.data?.summary
    const notice = res.data?.notice
    ElMessage.success(
      notice
        ? `${res.message || '批量删除完成'}。${notice}`
        : res.message || `批量删除完成：成功 ${summary?.succeeded ?? targets.length} 张`,
    )
    if (summary?.failed > 0) {
      ElMessage.warning(`有 ${summary.failed} 张删除失败`)
    }
    if (images.value.length <= targets.length && pagination.page > 1) {
      pagination.page -= 1
    }
    loadImages()
  } finally {
    batchDeleting.value = false
  }
}

async function handleRestore(row) {
  await ElMessageBox.confirm(
    `确定恢复图片「${row.image_name}」吗？恢复后将重新出现在正常列表中。`,
    '确认恢复',
    { type: 'info', confirmButtonText: '恢复', cancelButtonText: '取消' },
  )
  await restoreImageApi(row.id)
  ElMessage.success('图片已恢复')
  loadImages()
}

async function loadDeletionPolicy() {
  try {
    const res = await fetchDeletionPolicyApi()
    deletionPolicy.value = res.data || deletionPolicy.value
  } catch {
    // keep defaults
  }
}

onMounted(async () => {
  if (!auth.isAdmin) {
    filters.scope = 'mine'
    filters.uploadUser = auth.username
  }
  await Promise.all([loadCategories(), loadDeletionPolicy()])
  await loadImages()
})
</script>

<template>
  <div class="image-list-page">
    <div class="page-card">
      <h2 class="page-title">图片列表</h2>
      <p class="page-desc">
        <template v-if="auth.isAdmin">
          可视化筛选图片元数据，支持预览、下载、编辑与逻辑删除。
          {{ deletionPolicy.summary || `逻辑删除后保留 ${deletionPolicy.retention_days} 天，到期自动永久删除。` }}
        </template>
        <template v-else>
          浏览服务器上的图片，支持预览与下载原文件。默认显示「我的上传」，可切换查看全部。
          仅可编辑/删除自己上传的图片。
        </template>
      </p>

      <el-form :inline="true" class="filter-form" @submit.prevent="handleSearch">
        <el-form-item v-if="!auth.isAdmin" label="范围">
          <el-radio-group v-model="filters.scope" @change="handleScopeChange">
            <el-radio-button value="mine">我的上传</el-radio-button>
            <el-radio-button value="all">全部图片</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="关键词">
          <el-input
            v-model="filters.keyword"
            :placeholder="auth.isAdmin ? '名称/路径/标签/上传人' : '名称/标签/上传人'"
            clearable
            style="width: 180px"
          />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="filters.categoryId" placeholder="全部" clearable style="width: 140px">
            <el-option
              v-for="cat in categories"
              :key="cat.id"
              :label="cat.category_name"
              :value="cat.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="filters.tags" placeholder="包含匹配" clearable style="width: 120px" />
        </el-form-item>
        <el-form-item label="后缀">
          <el-select v-model="filters.suffix" placeholder="全部" clearable style="width: 100px">
            <el-option label="jpg" value="jpg" />
            <el-option label="png" value="png" />
            <el-option label="gif" value="gif" />
            <el-option label="webp" value="webp" />
            <el-option label="bmp" value="bmp" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="auth.isAdmin" label="上传人">
          <el-input v-model="filters.uploadUser" clearable style="width: 120px" />
        </el-form-item>
        <el-form-item label="上传时间">
          <el-date-picker
            v-model="filters.dateRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 360px"
          />
        </el-form-item>
        <el-form-item v-if="auth.isAdmin" label="含已删">
          <el-switch v-model="filters.includeDeleted" @change="handleSearch" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div class="page-card table-panel">
      <div v-if="auth.isAdmin" class="table-toolbar">
        <span class="selection-hint">
          已选 <strong>{{ selectedActiveCount }}</strong> 张（仅统计未删除）
        </span>
        <el-button
          type="danger"
          plain
          :disabled="!canBatchDelete"
          :loading="batchDeleting"
          @click="handleBatchDelete"
        >
          批量删除
        </el-button>
      </div>

      <el-table
        ref="tableRef"
        v-loading="loading"
        :data="images"
        stripe
        border
        style="width: 100%"
        @selection-change="handleSelectionChange"
      >
        <el-table-column v-if="auth.isAdmin" type="selection" width="48" align="center" fixed="left" :selectable="rowSelectable" />
        <el-table-column label="预览" width="88" align="center" fixed="left">
          <template #default="{ row }">
            <ImagePreview
              :image-id="row.id"
              :image-path="row.image_path"
              :size="56"
              clickable
              @click="openPreview(row)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="image_name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column label="分类" width="100">
          <template #default="{ row }">
            {{ categoryMap[row.category_id] || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="tags" label="标签" min-width="100" show-overflow-tooltip />
        <el-table-column label="尺寸" width="100" align="center">
          <template #default="{ row }">
            {{ row.image_width }}×{{ row.image_height }}
          </template>
        </el-table-column>
        <el-table-column label="大小" width="90" align="right">
          <template #default="{ row }">{{ formatFileSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column prop="upload_user" label="上传人" width="100" show-overflow-tooltip />
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.upload_time) }}</template>
        </el-table-column>
        <el-table-column v-if="auth.isAdmin" prop="image_path" label="存储路径" min-width="200" show-overflow-tooltip />
        <el-table-column v-if="filters.includeDeleted" label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_delete ? 'danger' : 'success'" size="small">
              {{ row.is_delete ? '已删' : '正常' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="filters.includeDeleted" label="永久删除" min-width="160">
          <template #default="{ row }">
            <template v-if="row.is_delete && row.deletion_info">
              <span v-if="row.deletion_info.expired" class="text-danger">已超过保留期，可能随时清理</span>
              <span v-else>
                剩余 {{ formatDeletionRemaining(row.deletion_info) }}
                <br />
                <span class="text-muted">{{ row.deletion_info.purge_at }}</span>
              </span>
            </template>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right" align="center">
          <template #default="{ row }">
            <el-button v-if="!row.is_delete" link type="primary" :icon="View" @click="openPreview(row)">
              预览
            </el-button>
            <el-button v-if="!row.is_delete" link type="primary" :icon="Download" @click="handleDownload(row)">
              下载
            </el-button>
            <el-button v-if="!row.is_delete && canModifyRow(row)" link type="primary" :icon="Edit" @click="openEdit(row)">
              编辑
            </el-button>
            <el-button v-if="!row.is_delete && canModifyRow(row)" link type="danger" @click="handleDelete(row)">
              删除
            </el-button>
            <el-button
              v-if="row.is_delete && canModifyRow(row)"
              link
              type="success"
              :icon="RefreshRight"
              @click="handleRestore(row)"
            >
              恢复
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="pagination.page"
          v-model:page-size="pagination.pageSize"
          :total="pagination.total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </div>

    <el-dialog v-model="previewVisible" :title="previewTitle" width="80%" top="5vh" destroy-on-close @closed="closePreview">
      <div v-loading="previewLoading" class="preview-body">
        <img v-if="previewSrc" :src="previewSrc" alt="预览" class="preview-img" />
      </div>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑图片信息" width="480px" destroy-on-close>
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
.image-list-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-desc {
  margin: 0 0 16px;
  color: #606266;
  line-height: 1.6;
}

.filter-form {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 0;
}

.table-panel {
  overflow: hidden;
}

.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}

.selection-hint {
  color: #606266;
  font-size: 14px;
}

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.preview-body {
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-img {
  max-width: 100%;
  max-height: 75vh;
  object-fit: contain;
}

.text-muted {
  color: #909399;
  font-size: 12px;
}

.text-danger {
  color: #f56c6c;
  font-size: 13px;
}
</style>
