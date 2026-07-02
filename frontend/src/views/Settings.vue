<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchStorageStatsApi, formatFileSize } from '@/api/logs'
import { getSystemConfigApi, updateSystemConfigApi } from '@/api/config'

const loading = ref(false)
const saving = ref(false)
const statsLoading = ref(false)
const stats = ref(null)
const configMeta = ref({ editable: {}, readonly: {}, env_file: '' })

const form = reactive({
  UPLOAD_ROOT: '',
  MAX_UPLOAD_SIZE_MB: 20,
  THUMB_SIZE: 200,
  SQL_QUERY_TIMEOUT: 10,
  SQL_MAX_ROWS: 1000,
  SQL_REQUIRE_WHERE_FOR_SELECT_STAR: false,
  DELETED_IMAGE_RETENTION_DAYS: 30,
  LOG_RETENTION_DAYS: 90,
  IMAGE_ACCESS_TOKEN_TTL: 3600,
})

const editableFields = computed(() => Object.entries(configMeta.value.editable || {}))

function applyConfigToForm(editable) {
  Object.keys(form).forEach((key) => {
    if (editable[key]) {
      form[key] = editable[key].value
    }
  })
}

async function loadStats() {
  statsLoading.value = true
  try {
    const res = await fetchStorageStatsApi()
    stats.value = res.data
  } catch {
    stats.value = null
  } finally {
    statsLoading.value = false
  }
}

async function loadConfig() {
  loading.value = true
  try {
    const res = await getSystemConfigApi()
    configMeta.value = res.data || {}
    applyConfigToForm(configMeta.value.editable || {})
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  saving.value = true
  try {
    const payload = { ...form }
    const res = await updateSystemConfigApi(payload)
    configMeta.value = res.data || {}
    applyConfigToForm(configMeta.value.editable || {})
    ElMessage.success('系统设置已保存（部分路径类配置需重启后端后完全生效）')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadConfig(), loadStats()])
})
</script>

<template>
  <div class="settings-page">
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never" v-loading="statsLoading">
          <div class="stat-label">正常图片</div>
          <div class="stat-value">{{ stats?.image_active_count ?? '-' }}</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never" v-loading="statsLoading">
          <div class="stat-label">已逻辑删除</div>
          <div class="stat-value">{{ stats?.image_deleted_count ?? '-' }}</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never" v-loading="statsLoading">
          <div class="stat-label">图片元数据占用</div>
          <div class="stat-value">{{ stats ? formatFileSize(stats.image_total_bytes) : '-' }}</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never" v-loading="statsLoading">
          <div class="stat-label">upload 磁盘占用</div>
          <div class="stat-value">{{ stats ? formatFileSize(stats.upload_disk_bytes) : '-' }}</div>
        </el-card>
      </el-col>
    </el-row>

    <div class="page-card" v-loading="loading">
      <h2 class="page-title">系统设置</h2>
      <p class="page-desc">
        修改上传路径、文件大小限制、缩略图尺寸及 SQL / 维护相关参数。保存后写入
        <code>{{ configMeta.env_file || 'backend/.env' }}</code> 并立即作用于当前进程。
      </p>

      <el-form label-width="200px" class="settings-form" @submit.prevent="handleSave">
        <el-divider content-position="left">存储与上传</el-divider>

        <el-form-item label="上传根目录 (UPLOAD_ROOT)">
          <el-input v-model="form.UPLOAD_ROOT" placeholder="例如 E:/图像路径式数据库管理系统/upload" />
        </el-form-item>

        <el-form-item label="单文件大小上限 (MB)">
          <el-input-number v-model="form.MAX_UPLOAD_SIZE_MB" :min="1" :max="500" />
        </el-form-item>

        <el-form-item label="缩略图边长 (px)">
          <el-input-number v-model="form.THUMB_SIZE" :min="50" :max="800" :step="10" />
        </el-form-item>

        <el-divider content-position="left">SQL 查询</el-divider>

        <el-form-item label="查询超时 (秒)">
          <el-input-number v-model="form.SQL_QUERY_TIMEOUT" :min="1" :max="120" />
        </el-form-item>

        <el-form-item label="最大返回行数">
          <el-input-number v-model="form.SQL_MAX_ROWS" :min="10" :max="10000" :step="50" />
        </el-form-item>

        <el-form-item label="SELECT * 必须带 WHERE">
          <el-switch v-model="form.SQL_REQUIRE_WHERE_FOR_SELECT_STAR" />
        </el-form-item>

        <el-divider content-position="left">维护策略</el-divider>

        <el-form-item label="逻辑删除保留天数">
          <el-input-number v-model="form.DELETED_IMAGE_RETENTION_DAYS" :min="1" :max="365" />
        </el-form-item>

        <el-form-item label="操作日志保留天数">
          <el-input-number v-model="form.LOG_RETENTION_DAYS" :min="7" :max="3650" />
        </el-form-item>

        <el-form-item label="图片访问令牌有效期 (秒)">
          <el-input-number v-model="form.IMAGE_ACCESS_TOKEN_TTL" :min="60" :max="86400" :step="60" />
        </el-form-item>

        <el-divider content-position="left">只读信息</el-divider>

        <el-form-item
          v-for="(value, key) in configMeta.readonly || {}"
          :key="key"
          :label="key"
        >
          <el-input :model-value="String(value)" readonly />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="handleSave">保存设置</el-button>
          <el-button @click="loadConfig">重新加载</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stats-row {
  margin-bottom: 0;
}

.stat-label {
  color: #909399;
  font-size: 13px;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}

.page-desc {
  margin: 0 0 20px;
  color: #606266;
  line-height: 1.6;
}

.settings-form {
  max-width: 720px;
}

code {
  font-size: 12px;
  color: #606266;
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
