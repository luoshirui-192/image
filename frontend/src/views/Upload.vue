<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import ImagePreview from '@/components/ImagePreview.vue'
import { formatFileSize, uploadImagesApi } from '@/api/images'

const ACCEPT_TYPES = '.jpg,.jpeg,.png,.gif,.webp,.bmp'
const MAX_SIZE_MB = 20

const uploadRef = ref()
const fileList = ref([])
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

onBeforeUnmount(() => {
  revokeLocalPreviews()
})
</script>

<template>
  <div class="upload-page">
    <div class="page-card">
      <h2 class="page-title">图片上传</h2>
      <p class="page-desc">
        支持拖拽或多选上传，自动分层存储并写入数据库路径。
        允许格式：JPG / PNG / GIF / WebP / BMP，单文件最大 {{ MAX_SIZE_MB }}MB。
      </p>

      <el-form label-width="80px" class="upload-form">
        <el-form-item label="标签">
          <el-input
            v-model="tags"
            placeholder="多个标签用逗号分隔（可选）"
            maxlength="500"
            show-word-limit
            clearable
          />
        </el-form-item>
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
          <div class="el-upload__tip">已选 {{ pendingCount }} 个文件，点击「开始上传」</div>
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

    <div v-if="results?.items?.length" class="page-card results-card">
      <h3 class="section-title">上传结果</h3>
      <p v-if="results.summary" class="result-summary">
        共 {{ results.summary.total }} 个，成功 {{ results.summary.succeeded }}，失败 {{ results.summary.failed }}
      </p>
      <div class="result-grid">
        <div
          v-for="item in results.items"
          :key="item.filename"
          class="result-item"
          :class="{ failed: !item.success }"
        >
          <template v-if="item.success && item.image">
            <ImagePreview
              :image-id="item.image.id"
              :image-path="item.image.image_path"
              :image-name="item.image.image_name"
              :suffix="item.image.file_suffix"
              class="result-thumb"
            />
            <div class="result-meta">
              <div class="result-name" :title="item.filename">{{ item.filename }}</div>
              <div v-if="item.overwritten" class="result-tag">已覆盖</div>
            </div>
          </template>
          <template v-else>
            <div class="result-fail">
              <div class="result-name" :title="item.filename">{{ item.filename }}</div>
              <div class="result-error">{{ item.error || '上传失败' }}</div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.upload-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-card {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 20px 24px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.page-title {
  margin: 0 0 8px;
  font-size: 20px;
}

.page-desc {
  margin: 0 0 20px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.upload-form {
  margin-bottom: 8px;
}

.upload-drop {
  width: 100%;
}

.upload-drop :deep(.el-upload-dragger) {
  width: 100%;
  padding: 28px 16px;
}

.upload-icon {
  font-size: 48px;
  color: var(--el-color-primary);
  margin-bottom: 8px;
}

.upload-progress {
  margin-top: 16px;
}

.upload-actions {
  margin-top: 16px;
  display: flex;
  gap: 12px;
}

.upload-file-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.local-thumb {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 4px;
  flex-shrink: 0;
}

.file-meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.section-title {
  margin: 0 0 12px;
  font-size: 16px;
}

.result-summary {
  margin: 0 0 16px;
  color: var(--el-text-color-secondary);
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.result-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
}

.result-item.failed {
  border-color: var(--el-color-danger-light-5);
}

.result-thumb {
  width: 100%;
  aspect-ratio: 1;
}

.result-meta,
.result-fail {
  padding: 8px;
}

.result-name {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-tag {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-color-warning);
}

.result-error {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-color-danger);
}
</style>
