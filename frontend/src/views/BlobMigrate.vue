<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Plus, Refresh, Search } from '@element-plus/icons-vue'
import {
  createBlobMigrationSourceApi,
  createBlobTableViewApi,
  createCategoryApi,
  createExternalDbConnectionApi,
  deleteBlobMigrationSourceApi,
  deleteExternalDbConnectionApi,
  discoverBlobTablesApi,
  listBlobMigrationDatabasesApi,
  listBlobMigrationSourcesApi,
  listCategoriesApi,
  listExternalDbConnectionsApi,
  runBlobMigrationApi,
  testExternalDbConnectionApi,
  testSavedExternalDbConnectionApi,
} from '@/api/images'

const router = useRouter()

const databases = ref([])
const connections = ref([])
const discoveredTables = ref([])
const sources = ref([])
const categories = ref([])
const discovering = ref(false)
const saving = ref(false)
const savingView = ref(false)
const running = ref(false)
const runResult = ref(null)

const form = reactive({
  name: '',
  dbAlias: 'default',
  sourceTable: '',
  sourcePkColumn: 'id',
  blobColumn: '',
  nameColumn: '',
  suffixColumn: '',
  categoryId: null,
  tags: '',
  whereClause: '',
})

const runOptions = reactive({
  sourceId: null,
  batchSize: 50,
  dryRun: true,
  skipExisting: true,
})

const categoryDialogVisible = ref(false)
const categoryDialogSaving = ref(false)
const newCategoryForm = reactive({ category_name: '', sort: 0 })

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
const connSaving = ref(false)
const connTesting = ref(false)

const selectedDb = computed(() => databases.value.find((d) => d.alias === form.dbAlias))

function dbOptionLabel(db) {
  if (db.label) {
    return `${db.label} (${db.name}@${db.host || 'local'})`
  }
  return `${db.alias} (${db.name}@${db.host || 'local'})`
}

async function loadConnections() {
  try {
    const res = await listExternalDbConnectionsApi()
    connections.value = res.data || []
  } catch {
    connections.value = []
  }
}

async function loadDatabases() {
  try {
    const res = await listBlobMigrationDatabasesApi()
    databases.value = res.data || []
    if (!databases.value.some((d) => d.alias === form.dbAlias) && databases.value.length) {
      form.dbAlias = databases.value[0].alias
    }
  } catch {
    databases.value = [{ alias: 'default', label: '本系统库', name: 'default', host: '' }]
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
    await createExternalDbConnectionApi({
      name: connForm.name.trim(),
      host: connForm.host.trim(),
      port: Number(connForm.port) || 3306,
      db_name: connForm.db_name.trim(),
      username: connForm.username.trim(),
      password: connForm.password,
      charset: connForm.charset || 'utf8',
      remark: connForm.remark.trim(),
    })
    ElMessage.success('旧库连接已保存')
    connForm.password = ''
    await Promise.all([loadConnections(), loadDatabases()])
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

async function removeConnection(row) {
  try {
    await ElMessageBox.confirm(`确定删除连接「${row.name}」？`, '确认', { type: 'warning' })
    await deleteExternalDbConnectionApi(row.id)
    ElMessage.success('已删除')
    await Promise.all([loadConnections(), loadDatabases()])
  } catch {
    // cancelled or error handled globally
  }
}

function useConnection(row) {
  form.dbAlias = row.alias
}

async function loadCategories() {
  try {
    const res = await listCategoriesApi()
    categories.value = res.data || []
  } catch {
    categories.value = []
  }
}

async function loadSources() {
  try {
    const res = await listBlobMigrationSourcesApi()
    sources.value = res.data || []
    if (!runOptions.sourceId && sources.value.length) {
      runOptions.sourceId = sources.value[0].id
    }
  } catch {
    sources.value = []
  }
}

async function discoverTables() {
  discovering.value = true
  discoveredTables.value = []
  try {
    const res = await discoverBlobTablesApi({ dbAlias: form.dbAlias })
    discoveredTables.value = res.data?.tables || []
    if (!discoveredTables.value.length) {
      ElMessage.info('未发现含 BLOB 的表')
    }
  } catch (err) {
    ElMessage.error(err.message || '扫描失败')
  } finally {
    discovering.value = false
  }
}

function applyDiscovery(row, col) {
  form.sourceTable = row.table
  form.blobColumn = col.column
}

async function saveView() {
  if (!form.sourceTable || !form.blobColumn) {
    ElMessage.warning('请填写源表与 BLOB 列')
    return
  }

  savingView.value = true
  try {
    const res = await createBlobTableViewApi({
      name: form.name.trim() || `${form.sourceTable} 视图`,
      db_alias: form.dbAlias,
      source_table: form.sourceTable.trim(),
      source_pk_column: form.sourcePkColumn.trim() || 'id',
      blob_column: form.blobColumn.trim(),
      where_clause: form.whereClause.trim(),
    })
    ElMessage.success('表视图已保存')
    const viewId = res.data?.id
    if (viewId) {
      router.push({ path: '/blob-views', query: { viewId: String(viewId) } })
    }
  } catch (err) {
    ElMessage.error(err.message || '保存视图失败')
  } finally {
    savingView.value = false
  }
}

async function saveSource() {
  if (!form.sourceTable || !form.blobColumn) {
    ElMessage.warning('请填写源表与 BLOB 列')
    return
  }
  if (!form.categoryId) {
    ElMessage.warning('请选择分类')
    return
  }

  saving.value = true
  try {
    await createBlobMigrationSourceApi({
      name: form.name.trim() || `${form.sourceTable}.${form.blobColumn}`,
      db_alias: form.dbAlias,
      source_table: form.sourceTable.trim(),
      source_pk_column: form.sourcePkColumn.trim() || 'id',
      blob_column: form.blobColumn.trim(),
      name_column: form.nameColumn.trim(),
      suffix_column: form.suffixColumn.trim(),
      category_id: form.categoryId,
      tags: form.tags.trim(),
      where_clause: form.whereClause.trim(),
    })
    ElMessage.success('迁移配置已保存')
    await loadSources()
  } catch (err) {
    ElMessage.error(err.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function removeSource(id) {
  try {
    await ElMessageBox.confirm('删除配置不会撤销已迁移的数据，确定删除？', '确认', { type: 'warning' })
    await deleteBlobMigrationSourceApi(id)
    ElMessage.success('已删除')
    if (runOptions.sourceId === id) {
      runOptions.sourceId = null
    }
    await loadSources()
  } catch {
    // cancelled
  }
}

async function executeMigration() {
  if (!runOptions.sourceId) {
    ElMessage.warning('请选择迁移任务')
    return
  }

  running.value = true
  runResult.value = null
  try {
    const res = await runBlobMigrationApi({
      sourceId: runOptions.sourceId,
      batchSize: runOptions.batchSize,
      dryRun: runOptions.dryRun,
      skipExisting: runOptions.skipExisting,
    })
    runResult.value = res.data
    ElMessage.success(res.message || '执行完成')
    await loadSources()
  } catch (err) {
    if (err.data) {
      runResult.value = err.data
    }
    ElMessage.error(err.message || '执行失败')
  } finally {
    running.value = false
  }
}

function openCreateCategory() {
  newCategoryForm.category_name = ''
  newCategoryForm.sort = 0
  categoryDialogVisible.value = true
}

async function submitCreateCategory() {
  const name = newCategoryForm.category_name.trim()
  if (!name) {
    ElMessage.warning('请输入分类名称')
    return
  }
  categoryDialogSaving.value = true
  try {
    const res = await createCategoryApi({
      category_name: name,
      sort: Number(newCategoryForm.sort) || 0,
    })
    ElMessage.success('分类已创建')
    categoryDialogVisible.value = false
    await loadCategories()
    if (res.data?.id) {
      form.categoryId = res.data.id
    }
  } finally {
    categoryDialogSaving.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadConnections(), loadDatabases(), loadCategories(), loadSources()])
})
</script>

<template>
  <div class="migrate-page">
    <div class="page-card">
      <h2 class="page-title">数据库 BLOB 迁移</h2>
      <p class="page-desc">
        可在下方<strong>直接添加旧库连接</strong>（无需改 .env），然后从旧表 BLOB 列导出到
        <code>upload/</code> 并写入 <code>image_info</code>；原表结构<strong>不会修改</strong>。
      </p>

      <el-alert
        title="管理员专用。先添加并测试旧库连接，再扫描 BLOB 表。建议先预检，再正式迁移。"
        type="warning"
        show-icon
        :closable="false"
        class="info-alert"
      />

      <section class="section">
        <h3>1. 连接旧库</h3>
        <el-form label-width="110px" class="compact-form">
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item label="连接名称" required>
                <el-input v-model="connForm.name" placeholder="例如：生产旧库" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="主机" required>
                <el-input
                  v-model="connForm.host"
                  placeholder="192.168.1.154 或 host.docker.internal"
                  clearable
                />
                <div class="field-hint">Docker 部署时，本机 MySQL 请填 <code>host.docker.internal</code> 或局域网 IP，不要用 127.0.0.1</div>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="端口">
                <el-input-number v-model="connForm.port" :min="1" :max="65535" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="数据库" required>
                <el-input v-model="connForm.db_name" placeholder="legacy_db" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="用户名" required>
                <el-input v-model="connForm.username" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="密码" required>
                <el-input v-model="connForm.password" type="password" show-password />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="备注">
                <el-input v-model="connForm.remark" maxlength="500" clearable />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item>
            <el-button type="primary" plain :loading="connTesting" @click="testNewConnection">
              测试连接
            </el-button>
            <el-button type="primary" :loading="connSaving" @click="saveConnection">
              保存连接
            </el-button>
          </el-form-item>
        </el-form>

        <el-table :data="connections" size="small" border empty-text="尚未配置旧库连接">
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column label="地址" min-width="180">
            <template #default="{ row }">{{ row.username }}@{{ row.host }}:{{ row.port }}/{{ row.db_name }}</template>
          </el-table-column>
          <el-table-column label="最近测试" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.last_test_ok === 1" type="success" size="small">成功</el-tag>
              <el-tag v-else-if="row.last_test_at" type="danger" size="small">失败</el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button link type="primary" @click="useConnection(row)">选用</el-button>
              <el-button link type="primary" :loading="connTesting" @click="testSavedConnection(row)">测试</el-button>
              <el-button link type="danger" @click="removeConnection(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="section">
        <h3>2. 选择数据源并扫描</h3>
        <el-form label-width="110px" class="compact-form">
          <el-form-item label="数据库">
            <el-select v-model="form.dbAlias" style="min-width: 320px">
              <el-option
                v-for="db in databases"
                :key="db.alias"
                :label="dbOptionLabel(db)"
                :value="db.alias"
              />
            </el-select>
            <el-button
              type="primary"
              plain
              :loading="discovering"
              class="ml-8"
              @click="discoverTables"
            >
              <el-icon><Search /></el-icon>
              扫描 BLOB 表
            </el-button>
          </el-form-item>
          <div v-if="selectedDb" class="field-hint">
            当前：<code>{{ selectedDb.alias }}</code>
            <span v-if="selectedDb.type === 'external'">（Web 配置的旧库）</span>
            <span v-else-if="selectedDb.type === 'system'">（本系统库，旧表若在同一库可选此项）</span>
          </div>
        </el-form>

        <el-table
          v-if="discoveredTables.length"
          :data="discoveredTables"
          size="small"
          border
          class="discover-table"
        >
          <el-table-column prop="table" label="表名" width="200" />
          <el-table-column label="BLOB 列">
            <template #default="{ row }">
              <el-tag
                v-for="col in row.columns"
                :key="col.column"
                class="col-tag"
                type="info"
                @click="applyDiscovery(row, col)"
              >
                {{ col.column }} ({{ col.data_type }})
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="discoveredTables.length" class="field-hint">点击列名可填入下方表单</p>
      </section>

      <section class="section">
        <h3>3. 配置迁移任务</h3>
        <el-form label-width="110px" class="compact-form">
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item label="任务名称">
                <el-input v-model="form.name" placeholder="可选" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="源表" required>
                <el-input v-model="form.sourceTable" placeholder="legacy_images" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="主键列">
                <el-input v-model="form.sourcePkColumn" placeholder="id" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="BLOB 列" required>
                <el-input v-model="form.blobColumn" placeholder="image_data" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="文件名列">
                <el-input v-model="form.nameColumn" placeholder="可选" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="后缀列">
                <el-input v-model="form.suffixColumn" placeholder="可选" clearable />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="16">
              <el-form-item label="分类" required>
                <div class="category-row">
                  <el-select v-model="form.categoryId" placeholder="请选择" filterable style="width: 100%">
                    <el-option
                      v-for="cat in categories"
                      :key="cat.id"
                      :label="cat.category_name"
                      :value="cat.id"
                    />
                  </el-select>
                  <el-button type="primary" plain @click="openCreateCategory">
                    <el-icon><Plus /></el-icon>
                  </el-button>
                </div>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="24">
              <el-form-item label="WHERE 条件">
                <el-input
                  v-model="form.whereClause"
                  placeholder="例如：status = 1（不含 WHERE 关键字）"
                  clearable
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="24">
              <el-form-item label="标签">
                <el-input v-model="form.tags" placeholder="写入 image_info.tags" maxlength="500" clearable />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item>
            <el-button type="primary" :loading="saving" @click="saveSource">
              <el-icon><Connection /></el-icon>
              保存迁移配置
            </el-button>
            <el-button type="success" plain :loading="savingView" @click="saveView">
              保存为表视图
            </el-button>
            <span class="field-hint inline-hint">表视图仅用于浏览远程数据，BLOB 列显示为本地路径，不执行迁移</span>
          </el-form-item>
        </el-form>
      </section>

      <section class="section">
        <h3>4. 已保存的任务</h3>
        <el-table :data="sources" size="small" border empty-text="暂无配置">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column label="源" min-width="180">
            <template #default="{ row }">
              {{ row.db_alias }} · {{ row.source_table }}.{{ row.blob_column }}
            </template>
          </el-table-column>
          <el-table-column label="进度" min-width="160">
            <template #default="{ row }">
              <span v-if="row.stats">
                已迁移 {{ row.stats.migrated }} / 共 {{ row.stats.total_with_blob }}
                （待处理 {{ row.stats.pending }}）
              </span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button link type="primary" @click="runOptions.sourceId = row.id">选用</el-button>
              <el-button link type="danger" @click="removeSource(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="section">
        <h3>5. 执行迁移</h3>
        <el-form inline class="run-form">
          <el-form-item label="任务">
            <el-select v-model="runOptions.sourceId" placeholder="选择任务" style="min-width: 220px">
              <el-option
                v-for="src in sources"
                :key="src.id"
                :label="`${src.id}: ${src.name || src.source_table}`"
                :value="src.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="批次大小">
            <el-input-number v-model="runOptions.batchSize" :min="1" :max="500" />
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="runOptions.dryRun">仅预检（不写盘）</el-checkbox>
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="runOptions.skipExisting">跳过已迁移</el-checkbox>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="running" @click="executeMigration">
              <el-icon><Refresh /></el-icon>
              {{ runOptions.dryRun ? '预检' : '开始迁移' }}
            </el-button>
          </el-form-item>
        </el-form>

        <el-table
          v-if="runResult?.items?.length"
          :data="runResult.items"
          size="small"
          border
          class="result-table"
          max-height="320"
        >
          <el-table-column prop="source_id" label="源 ID" width="100" />
          <el-table-column prop="filename" label="文件名" min-width="160" />
          <el-table-column label="结果" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.skipped" type="info">跳过</el-tag>
              <el-tag v-else-if="row.success" type="success">成功</el-tag>
              <el-tag v-else type="danger">失败</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="image_info_id" label="image_info" width="100" />
          <el-table-column prop="error" label="说明" min-width="160" show-overflow-tooltip />
        </el-table>
      </section>
    </div>

    <el-dialog v-model="categoryDialogVisible" title="新建分类" width="400px">
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="newCategoryForm.category_name" maxlength="100" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="newCategoryForm.sort" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="categoryDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="categoryDialogSaving" @click="submitCreateCategory">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.migrate-page {
  max-width: 1100px;
}

.page-card {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 24px;
  box-shadow: 0 1px 4px rgb(0 0 0 / 6%);
}

.page-title {
  margin: 0 0 8px;
  font-size: 20px;
}

.page-desc {
  margin: 0 0 16px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.info-alert {
  margin-bottom: 20px;
}

.section {
  margin-bottom: 28px;
}

.section h3 {
  margin: 0 0 12px;
  font-size: 16px;
}

.field-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.inline-hint {
  margin-left: 12px;
  margin-top: 0;
}

.discover-table,
.result-table {
  margin-top: 12px;
}

.col-tag {
  margin: 2px 6px 2px 0;
  cursor: pointer;
}

.category-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.ml-8 {
  margin-left: 8px;
}

.run-form {
  flex-wrap: wrap;
}
</style>
