<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import ImagePreview from '@/components/ImagePreview.vue'
import { formatFileSize, listCategoriesApi, uploadImagesApi } from '@/api/images'

const ACCEPT_TYPES = '.jpg,.jpeg,.png,.gif,.webp,.bmp'
const MAX_SIZE_MB = 20

const uploadRef = ref()
const fileList = ref([])
const categories = ref([])
const categoryId = ref(null)
const tags = ref('')
const uploading = ref(false)
const uploadProgress = ref(0)
const results = ref(null)

const localPreviews = ref(new Map())

const pendingCount = computed(() => fileList.value.length)
const canUpload = computed(() => pendingCount.value > 0 && !uploading.value)

function rememberLocalPreview(file) {
  if (!localPreviews.value.has(file.uid)) {
    localPreviews.value.set(file.uid, URL.createObjectURL(file.raw))
  }
  return localPreviews.value.get(file.uid)
}

function revokeLocalPreviews() {
  localPreviews.value.forEach((url) => URL.revokeObjectURL(url))
  localPreviews.value.clear()
}

function beforeUpload(file) {
  const ext = file.name.split('.').pop()?.toLowerCase()
  const allowed = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
  if (!ext || !allowed.includes(ext)) {
    ElMessage.warning(`不支持的文件类型：${file.name}`)
    return false
  }
  if (file.size > MAX_SIZE_MB * 1024 * 1024) {
    ElMessage.warning(`文件 ${file.name} 超过 ${MAX_SIZE_MB}MB 限制`)
    return false
  }
  return true
}

function onChange(_uploadFile, uploadFiles) {
  fileList.value = uploadFiles.filter((f) => f.status !== 'fail')
}

function onRemove(_file, uploadFiles) {
  fileList.value = uploadFiles
}

function clearFiles() {
  uploadRef.value?.clearFiles()
  fileList.value = []
  revokeLocalPreviews()
  results.value = null
  uploadProgress.value = 0
}

async function loadCategories() {
  try {
    const res = await listCategoriesApi()
    categories.value = res.data || []
  } catch {
    categories.value = []
  }
}

async function submitUpload(overwrite = false) {
  if (!canUpload.value) return

  const files = fileList.value.map((f) => f.raw).filter(Boolean)
  if (!files.length) {
    ElMessage.warning('请先选择图片')
    return
  }

  uploading.value = true
  uploadProgress.value = 10
  results.value = null

  try {
    uploadProgress.value = 40
    const res = await uploadImagesApi(files, {
      categoryId: categoryId.value,
      tags: tags.value.trim(),
      overwrite,
    })
    uploadProgress.value = 100
    results.value = res.data
    ElMessage.success(res.message || '上传完成')

    if (res.data?.summary?.failed === 0) {
      uploadRef.value?.clearFiles()
      fileList.value = []
      revokeLocalPreviews()
    }
  } catch (err) {
    uploadProgress.value = 0
    if (err.code === 4006 && err.data?.duplicates?.length) {
      const names = err.data.duplicates.map((item) => item.filename).join('、')
      try {
        await ElMessageBox.confirm(
          `以下图片已存在：${names}。是否覆盖原有数据？`,
          '发现重复图片',
          {
            confirmButtonText: '覆盖',
            cancelButtonText: '取消',
            type: 'warning',
          },
        )
        return submitUpload(true)
      } catch {
        ElMessage.info('已取消上传')
        return
      }
    }
    if (err.data) {
      results.value = err.data
    }
    ElMessage.error(err.message || '上传失败')
  } finally {
    uploading.value = false
    setTimeout(() => {
      if (uploadProgress.value === 100) {
        uploadProgress.value = 0
      }
    }, 800)
  }
}

loadCategories()

onBeforeUnmount(() => {
  revokeLocalPreviews()
})
</script>

<template>
  <div class="upload-page">
    <div class="page-card">
      <h2 class="page-title">图片上传</h2>
      <p class="page-desc">
        支持拖拽或多选上传，自动分层存储并写入数据库路径。允许格式：JPG / PNG / GIF / WebP / BMP，单文件最大 {{ MAX_SIZE_MB }}MB。
      </p>

      <el-form label-width="80px" class="upload-form">
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12">
            <el-form-item label="分类">
              <el-select v-model="categoryId" placeholder="选择分类（可选）" clearable style="width: 100%">
                <el-option
                  v-for="cat in categories"
                  :key="cat.id"
                  :label="cat.category_name"
                  :value="cat.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="标签">
              <el-input
                v-model="tags"
                placeholder="多个标签用逗号分隔"
                maxlength="500"
                show-word-limit
                clearable
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <el-upload
        ref="uploadRef"
        class="upload-drop"
        drag
        multiple
        :auto-upload="false"
        :accept="ACCEPT_TYPES"
        :before-upload="beforeUpload"
        :on-change="onChange"
        :on-remove="onRemove"
        :file-list="fileList"
        list-type="picture"
      >
        <el-icon class="upload-icon"><UploadFilled /></el-icon>
        <div class="el-upload__text">将图片拖到此处，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">已选 {{ pendingCount }} 个文件，确认后点击「开始上传」</div>
        </template>
        <template #file="{ file }">
          <div class="upload-file-item">
            <img :src="rememberLocalPreview(file)" :alt="file.name" class="local-thumb" />
            <div class="file-meta">
              <span class="file-name" :title="file.name">{{ file.name }}</span>
              <span class="file-size">{{ formatFileSize(file.size) }}</span>
            </div>
          </div>
        </template>
      </el-upload>

      <el-progress
        v-if="uploading || uploadProgress === 100"
        :percentage="uploadProgress"
        :status="uploadProgress === 100 ? 'success' : undefined"
        class="upload-progress"
      />

      <div class="upload-actions">
        <el-button type="primary" :loading="uploading" :disabled="!canUpload" @click="submitUpload">
          开始上传
        </el-button>
        <el-button :disabled="uploading || pendingCount === 0" @click="clearFiles">清空列表</el-button>
      </div>
    </div>

    <div v-if="results" class="page-card result-panel">
      <h3 class="section-title">上传结果</h3>
      <el-alert
        :title="`共 ${results.summary.total} 个，成功 ${results.summary.succeeded}，失败 ${results.summary.failed}`"
        :type="results.summary.failed > 0 ? 'warning' : 'success'"
        show-icon
        :closable="false"
        class="result-summary"
      />

      <el-table :data="results.items" stripe style="width: 100%">
        <el-table-column label="预览" width="100" align="center">
          <template #default="{ row }">
            <ImagePreview
              v-if="row.success && row.image"
              :image-id="row.image.id"
              :image-path="row.image.image_path"
              :size="64"
            />
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="filename" label="文件名" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.overwritten" type="warning" size="small">已覆盖</el-tag>
            <el-tag v-else :type="row.success ? 'success' : 'danger'" size="small">
              {{ row.success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="存储路径 / 错误" min-width="220">
          <template #default="{ row }">
            <span v-if="row.success && row.image" class="path-text">{{ row.image.image_path }}</span>
            <span v-else class="error-text">{{ row.error }}</span>
          </template>
        </el-table-column>
        <el-table-column label="尺寸" width="100" align="center">
          <template #default="{ row }">
            <span v-if="row.image">
              {{ row.image.image_width }}×{{ row.image.image_height }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="90" align="right">
          <template #default="{ row }">
            <span v-if="row.image">{{ formatFileSize(row.image.file_size) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.upload-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-desc {
  margin: 0 0 20px;
  color: #606266;
  line-height: 1.6;
}

.upload-form {
  margin-bottom: 8px;
}

.upload-drop {
  width: 100%;
}

.upload-drop :deep(.el-upload-dragger) {
  padding: 32px 20px;
}

.upload-icon {
  font-size: 48px;
  color: #409eff;
  margin-bottom: 8px;
}

.upload-file-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
}

.local-thumb {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid #ebeef5;
}

.file-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.file-name {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  font-size: 12px;
  color: #909399;
}

.upload-progress {
  margin-top: 16px;
}

.upload-actions {
  margin-top: 16px;
  display: flex;
  gap: 12px;
}

.section-title {
  margin: 0 0 16px;
  font-size: 16px;
  font-weight: 600;
}

.result-summary {
  margin-bottom: 16px;
}

.path-text {
  font-family: Consolas, monospace;
  font-size: 12px;
  color: #606266;
  word-break: break-all;
}

.error-text {
  color: #f56c6c;
  font-size: 13px;
}

.text-muted {
  color: #c0c4cc;
}
</style>
