<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, View } from '@element-plus/icons-vue'
import {
  actionTypeLabel,
  formatDateTime,
  listLogsApi,
  LOG_ACTION_TYPES,
} from '@/api/logs'
import { usePageDataRefresh } from '@/utils/usePageDataRefresh'

const loading = ref(false)
const logs = ref([])
const pagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
})

const filters = reactive({
  username: '',
  actionType: '',
  keyword: '',
  dateRange: null,
})

const sqlDialogVisible = ref(false)
const sqlDialogTitle = ref('')
const sqlDialogContent = ref('')

function buildQueryParams() {
  const params = {
    page: pagination.page,
    page_size: pagination.pageSize,
  }
  if (filters.username.trim()) params.username = filters.username.trim()
  if (filters.actionType) params.action_type = filters.actionType
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim()
  if (filters.dateRange?.length === 2) {
    params.create_time_from = filters.dateRange[0]
    params.create_time_to = filters.dateRange[1]
  }
  return params
}

async function loadLogs() {
  loading.value = true
  try {
    const res = await listLogsApi(buildQueryParams())
    const data = res.data || {}
    logs.value = data.results || []
    pagination.total = data.count || 0
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  pagination.page = 1
  loadLogs()
}

function handleReset() {
  filters.username = ''
  filters.actionType = ''
  filters.keyword = ''
  filters.dateRange = null
  handleSearch()
}

function handlePageChange(page) {
  pagination.page = page
  loadLogs()
}

function handleSizeChange(size) {
  pagination.pageSize = size
  pagination.page = 1
  loadLogs()
}

function openSqlDialog(row) {
  sqlDialogTitle.value = `${row.username} · ${actionTypeLabel(row.action_type)} · ${formatDateTime(row.create_time)}`
  sqlDialogContent.value = row.sql_content || ''
  sqlDialogVisible.value = true
}

function copySql() {
  if (!sqlDialogContent.value) {
    ElMessage.warning('无 SQL 内容')
    return
  }
  navigator.clipboard.writeText(sqlDialogContent.value).then(
    () => ElMessage.success('已复制到剪贴板'),
    () => ElMessage.error('复制失败'),
  )
}

usePageDataRefresh(loadLogs, {
  isEmpty: () => !logs.value.length,
  alwaysRefreshOnVisible: true,
})
</script>

<template>
  <div class="logs-page">
    <div class="page-card">
      <h2 class="page-title">操作日志</h2>
      <p class="page-desc">查看用户登录、图片上传/删除、SQL 执行等操作记录，支持按用户、类型与时间筛选。</p>

      <el-form :inline="true" class="filter-form" @submit.prevent="handleSearch">
        <el-form-item label="用户名">
          <el-input v-model="filters.username" placeholder="模糊匹配" clearable style="width: 140px" />
        </el-form-item>
        <el-form-item label="操作类型">
          <el-select v-model="filters.actionType" placeholder="全部" clearable style="width: 140px">
            <el-option
              v-for="item in LOG_ACTION_TYPES"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词">
          <el-input
            v-model="filters.keyword"
            placeholder="详情/SQL/IP"
            clearable
            style="width: 160px"
          />
        </el-form-item>
        <el-form-item label="时间范围">
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
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>

      <div class="table-panel">
        <el-table v-loading="loading" :data="logs" stripe border style="width: 100%">
          <el-table-column prop="id" label="ID" width="72" />
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatDateTime(row.create_time) }}</template>
          </el-table-column>
          <el-table-column prop="username" label="用户" width="110" show-overflow-tooltip />
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ actionTypeLabel(row.action_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="detail" label="详情" min-width="220" show-overflow-tooltip />
          <el-table-column prop="ip" label="IP" width="130" show-overflow-tooltip />
          <el-table-column label="SQL" width="90" align="center">
            <template #default="{ row }">
              <el-button
                v-if="row.sql_content"
                link
                type="primary"
                :icon="View"
                @click="openSqlDialog(row)"
              >
                查看
              </el-button>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="pagination.page"
            v-model:page-size="pagination.pageSize"
            :total="pagination.total"
            :page-sizes="[10, 20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            background
            @current-change="handlePageChange"
            @size-change="handleSizeChange"
          />
        </div>
      </div>
    </div>

    <el-dialog v-model="sqlDialogVisible" :title="sqlDialogTitle" width="720px" destroy-on-close>
      <el-input
        v-model="sqlDialogContent"
        type="textarea"
        :rows="14"
        readonly
        class="sql-textarea"
      />
      <template #footer>
        <el-button @click="sqlDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="copySql">复制 SQL</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.logs-page {
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

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.muted {
  color: #c0c4cc;
}

.sql-textarea :deep(textarea) {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 13px;
}
</style>
