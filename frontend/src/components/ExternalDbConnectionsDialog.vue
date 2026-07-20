<script setup>
/**
 * External DB connection admin (create / test / provision / delete).
 * Used by 数据库模拟; BLOB 迁移任务台不再重复此向导。
 */
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { callWithRetry } from '@/utils/callWithRetry'
import {
  createExternalDbConnectionApi,
  deleteExternalDbConnectionApi,
  listExternalDbConnectionsApi,
  provisionExternalDbTableViewsApi,
  testExternalDbConnectionApi,
  testSavedExternalDbConnectionApi,
} from '@/api/images'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const visible = ref(false)
const connections = ref([])
const loading = ref(false)
const connSaving = ref(false)
const connTesting = ref(false)
const provisionConnId = ref(null)

const connForm = reactive({
  name: '',
  host: '',
  port: 3306,
  db_name: '',
  username: '',
  password: '',
  charset: 'utf8',
  remark: '',
})

watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
    if (v) void loadConnections()
  },
  { immediate: true },
)

watch(visible, (v) => {
  emit('update:modelValue', v)
})

async function loadConnections() {
  loading.value = true
  try {
    const res = await callWithRetry(() => listExternalDbConnectionsApi())
    connections.value = res.data || []
  } catch {
    connections.value = []
  } finally {
    loading.value = false
  }
}

async function saveConnection() {
  if (!connForm.name.trim() || !connForm.host.trim() || !connForm.db_name.trim() || !connForm.username.trim()) {
    ElMessage.warning('请填写连接名称、主机、库名和用户名')
    return
  }
  if (!connForm.password) {
    ElMessage.warning('请填写密码')
    return
  }
  connSaving.value = true
  try {
    const res = await createExternalDbConnectionApi({
      name: connForm.name.trim(),
      host: connForm.host.trim(),
      port: Number(connForm.port) || 3306,
      db_name: connForm.db_name.trim(),
      username: connForm.username.trim(),
      password: connForm.password,
      charset: connForm.charset || 'utf8',
      remark: connForm.remark.trim(),
    })
    ElMessage.success(res.message || '旧库连接已保存')
    connForm.password = ''
    await loadConnections()
    emit('changed')
  } catch (err) {
    ElMessage.error(err.message || '保存失败')
  } finally {
    connSaving.value = false
  }
}

async function testNewConnection() {
  if (!connForm.host.trim() || !connForm.db_name.trim() || !connForm.username.trim() || !connForm.password) {
    ElMessage.warning('测试连接需填写主机、库名、用户名和密码')
    return
  }
  connTesting.value = true
  try {
    const res = await testExternalDbConnectionApi({
      name: connForm.name.trim() || 'test',
      host: connForm.host.trim(),
      port: Number(connForm.port) || 3306,
      db_name: connForm.db_name.trim(),
      username: connForm.username.trim(),
      password: connForm.password,
      charset: connForm.charset || 'utf8',
    })
    ElMessage.success(res.message || '连接成功')
  } catch (err) {
    ElMessage.error(err.message || '连接失败')
  } finally {
    connTesting.value = false
  }
}

async function testSavedConnection(row) {
  connTesting.value = true
  try {
    const res = await testSavedExternalDbConnectionApi(row.id)
    ElMessage.success(res.message || '连接成功')
    await loadConnections()
  } catch (err) {
    ElMessage.error(err.message || '连接失败')
    await loadConnections()
  } finally {
    connTesting.value = false
  }
}

async function syncConnectionTableViews(row) {
  provisionConnId.value = row.id
  try {
    const res = await provisionExternalDbTableViewsApi(row.id)
    ElMessage.success(res.message || '表视图同步完成')
    emit('changed')
  } catch (err) {
    ElMessage.error(err.message || '表视图同步失败')
  } finally {
    provisionConnId.value = null
  }
}

async function removeConnection(row) {
  try {
    await ElMessageBox.confirm(`确定删除连接「${row.name}」？`, '确认', { type: 'warning' })
    await deleteExternalDbConnectionApi(row.id)
    ElMessage.success('已删除')
    await loadConnections()
    emit('changed')
  } catch {
    // cancelled
  }
}

onMounted(() => {
  if (props.modelValue) void loadConnections()
})
</script>

<template>
  <el-dialog
    v-model="visible"
    title="旧库连接管理"
    width="780px"
    destroy-on-close
  >
    <p class="hint">
      添加外部 MySQL 连接后，左侧目录会自动出现对应库。Docker 访问宿主机 MySQL 请用
      <code>host.docker.internal</code> 或局域网 IP，不要用 127.0.0.1。
    </p>
    <el-form label-width="90px" class="conn-form">
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="连接名称" required>
            <el-input v-model="connForm.name" placeholder="例如：生产旧库" clearable />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="主机" required>
            <el-input v-model="connForm.host" placeholder="192.168.x.x" clearable />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="端口">
            <el-input-number v-model="connForm.port" :min="1" :max="65535" style="width: 100%" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="数据库" required>
            <el-input v-model="connForm.db_name" clearable />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="用户名" required>
            <el-input v-model="connForm.username" clearable />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="密码" required>
            <el-input v-model="connForm.password" type="password" show-password />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="备注">
            <el-input v-model="connForm.remark" maxlength="500" clearable />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item>
        <el-button type="primary" plain :loading="connTesting" @click="testNewConnection">测试连接</el-button>
        <el-button type="primary" :loading="connSaving" @click="saveConnection">保存连接</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="connections" size="small" border empty-text="尚未配置旧库连接">
      <el-table-column prop="name" label="名称" min-width="120" />
      <el-table-column label="地址" min-width="200">
        <template #default="{ row }">
          {{ row.username }}@{{ row.host }}:{{ row.port }}/{{ row.db_name }}
        </template>
      </el-table-column>
      <el-table-column label="最近测试" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.last_test_ok === 1" type="success" size="small">成功</el-tag>
          <el-tag v-else-if="row.last_test_at" type="danger" size="small">失败</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button link type="primary" :loading="connTesting" @click="testSavedConnection(row)">测试</el-button>
          <el-button
            link
            type="primary"
            :loading="provisionConnId === row.id"
            @click="syncConnectionTableViews(row)"
          >
            同步表视图
          </el-button>
          <el-button link type="danger" @click="removeConnection(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>
</template>

<style scoped>
.hint {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.conn-form {
  margin-bottom: 12px;
}
</style>
