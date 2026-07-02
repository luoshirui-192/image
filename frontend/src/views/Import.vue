<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderOpened } from '@element-plus/icons-vue'
import ImagePreview from '@/components/ImagePreview.vue'
import { formatFileSize, importImagesApi, listCategoriesApi } from '@/api/images'

const categories = ref([])
const form = ref({
  directory: '',
  categoryId: null,
  tags: '',
  recursive: false,
})
const importing = ref(false)
const results = ref(null)

async function loadCategories() {
  try {
    const res = await listCategoriesApi()
    categories.value = res.data || []
  } catch {
    categories.value = []
  }
}

async function submitImport(overwrite = false) {
  const directory = form.value.directory.trim()
  if (!directory) {
    ElMessage.warning('请输入服务器上的目录路径')
    return
  }

  importing.value = true
  results.value = null

  try {
    const res = await importImagesApi({
      directory,
      categoryId: form.value.categoryId,
      tags: form.value.tags.trim(),
      recursive: form.value.recursive,
      overwrite,
    })
    results.value = res.data
    ElMessage.success(res.message || '导入完成')
  } catch (err) {
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
        return submitImport(true)
      } catch {
        ElMessage.info('已取消导入')
        return
      }
    }
    if (err.data) {
      results.value = err.data
    }
    ElMessage.error(err.message || '导入失败')
  } finally {
    importing.value = false
  }
}

function resetForm() {
  form.value.directory = ''
  form.value.categoryId = null
  form.value.tags = ''
  form.value.recursive = false
  results.value = null
}

loadCategories()
</script>

<template>
  <div class="import-page">
    <div class="page-card">
      <h2 class="page-title">批量导入</h2>
      <p class="page-desc">
        扫描<strong>服务器本地目录</strong>中的图片文件，复制到分层存储并写入数据库。
        路径必须在项目根目录下（相对路径或绝对路径均可），不能从 <code>upload/</code> 目录导入。
      </p>

      <el-alert
        title="此功能仅管理员可用。目录需在服务器上可访问，前端无法浏览服务器文件系统。"
        type="info"
        show-icon
        :closable="false"
        class="info-alert"
      />

      <el-form label-width="100px" class="import-form" @submit.prevent="submitImport">
        <el-form-item label="目录路径" required>
          <el-input
            v-model="form.directory"
            placeholder="例如：import_samples 或 D:/data/photos"
            clearable
          >
            <template #prefix>
              <el-icon><FolderOpened /></el-icon>
            </template>
          </el-input>
          <div class="field-hint">相对路径基于项目根目录；支持 jpg/png/gif/webp/bmp</div>
        </el-form-item>

        <el-row :gutter="16">
          <el-col :xs="24" :sm="12">
            <el-form-item label="分类">
              <el-select v-model="form.categoryId" placeholder="选择分类（可选）" clearable style="width: 100%">
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
                v-model="form.tags"
                placeholder="多个标签用逗号分隔"
                maxlength="500"
                clearable
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="扫描选项">
          <el-checkbox v-model="form.recursive">递归扫描子目录</el-checkbox>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="importing" @click="submitImport">
            开始导入
          </el-button>
          <el-button :disabled="importing" @click="resetForm">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="results" class="page-card result-panel">
      <h3 class="section-title">导入结果</h3>
      <el-alert
        :title="`共 ${results.summary.total} 个，成功 ${results.summary.succeeded}，失败 ${results.summary.failed}`"
        :type="results.summary.failed > 0 ? 'warning' : 'success'"
        show-icon
        :closable="false"
        class="result-summary"
      />

      <el-table :data="results.items" stripe max-height="480" style="width: 100%">
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
        <el-table-column prop="filename" label="文件名" min-width="140" show-overflow-tooltip />
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'" size="small">
              {{ row.success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="存储路径 / 错误" min-width="240">
          <template #default="{ row }">
            <span v-if="row.success && row.image" class="path-text">{{ row.image.image_path }}</span>
            <span v-else class="error-text">{{ row.error }}</span>
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
.import-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-desc {
  margin: 0 0 16px;
  color: #606266;
  line-height: 1.6;
}

.page-desc code {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}

.info-alert {
  margin-bottom: 20px;
}

.import-form {
  max-width: 720px;
}

.field-hint {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.4;
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
