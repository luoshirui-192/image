<script setup>
/**
 * Shared batmatch zip import dialog (path writeback optional).
 * Emits `started` with job payload after queueing.
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listBlobCatalogConnectionsApi } from '@/api/images'
import { importFingerprintZipApi } from '@/api/fingerprints'
import { connectionKey, pickPreferredConnection } from '@/utils/dbConnection'

const visible = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['started'])

const submitting = ref(false)
const importFile = ref(null)
const importVersion = ref('1.0')
const importFailOnDuplicates = ref(false)
const wbEnabled = ref(false)
const wbLoading = ref(false)
const wbConnections = ref([])
const wbConnectionKey = ref('')

const selectedWbConnection = computed(
  () => wbConnections.value.find((c) => connectionKey(c) === wbConnectionKey.value) || null,
)

function resetForm() {
  importFile.value = null
  importVersion.value = '1.0'
  importFailOnDuplicates.value = false
  wbEnabled.value = false
  wbConnectionKey.value = ''
}

async function ensureConnections() {
  wbLoading.value = true
  try {
    const res = await listBlobCatalogConnectionsApi()
    wbConnections.value = res.data || []
    const fallback = pickPreferredConnection(wbConnections.value)
    if (fallback && !wbConnectionKey.value) {
      wbConnectionKey.value = connectionKey(fallback)
    }
  } catch (err) {
    ElMessage.error(err.message || '加载数据库连接失败')
  } finally {
    wbLoading.value = false
  }
}

function buildPathWritebackPayload() {
  if (!wbEnabled.value) return null
  const conn = selectedWbConnection.value
  if (!conn) {
    throw new Error('启用路径写回时请选择数据库连接（需能访问 ara_fp_analyst）')
  }
  const payload = {
    enabled: true,
    database: 'ara_fp_analyst',
    dataset_code: 'PK_5W',
  }
  if (conn.connection_id != null) {
    payload.connection_id = conn.connection_id
  } else {
    payload.db_alias = conn.alias || 'default'
  }
  return payload
}

function onImportFileChange(uploadFile) {
  importFile.value = uploadFile.raw || null
}

watch(visible, (open) => {
  if (open) {
    resetForm()
    void ensureConnections()
  }
})

watch(wbEnabled, (on) => {
  if (on) void ensureConnections()
})

async function submitImport() {
  if (!importFile.value) {
    ElMessage.warning('请选择 zip 文件')
    return
  }
  const ver = (importVersion.value || '').trim()
  if (!ver) {
    ElMessage.warning('请填写算法版本')
    return
  }
  let pathWriteback = null
  try {
    pathWriteback = buildPathWritebackPayload()
  } catch (err) {
    ElMessage.warning(err.message || '路径写回配置不完整')
    return
  }
  submitting.value = true
  try {
    const res = await importFingerprintZipApi(importFile.value, {
      algo_version: ver,
      skip_existing: true,
      fail_on_duplicates: importFailOnDuplicates.value,
      path_writeback: pathWriteback,
    })
    const job = res?.data?.job
    if (!job?.id) {
      ElMessage.error('未拿到导入任务')
      return
    }
    visible.value = false
    emit('started', job)
  } catch (err) {
    ElMessage.error(err.message || '启动导入失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="导入 batmatch zip" width="640px">
    <p class="dialog-tip">
      导入仍写入本系统图库与配对表；开启<strong>路径写回</strong>后才会进入业务表，指纹浏览左侧树才能看到样本。
    </p>
    <el-form label-width="110px" v-loading="wbLoading">
      <el-form-item label="算法版本" required>
        <el-input v-model="importVersion" placeholder="例如 1.0 / 2.0 / bidiso-2024" />
      </el-form-item>
      <el-form-item label="zip 文件" required>
        <el-upload
          :auto-upload="false"
          :show-file-list="true"
          :limit="1"
          accept=".zip"
          :on-change="onImportFileChange"
        >
          <el-button>选择文件</el-button>
        </el-upload>
      </el-form-item>
      <el-form-item label="严格模式">
        <el-checkbox v-model="importFailOnDuplicates">
          发现左右同图 / 同名覆盖时中止导入
        </el-checkbox>
      </el-form-item>

      <el-divider content-position="left">路径写回（浏览数据源）</el-divider>
      <p class="dialog-tip">
        固定写入 <code>ara_fp_analyst.T_CAP_FP_DATA</code> /
        <code>T_FEATURE_RECORD</code>； 图像路径进 <code>fingerprint_image</code>，
        Bidiso→<code>feature_ara_data</code>，Neuiso→<code>feature_neuro_data</code>。
      </p>
      <el-form-item label="启用写回">
        <el-switch v-model="wbEnabled" />
      </el-form-item>
      <template v-if="wbEnabled">
        <el-form-item label="数据库连接" required>
          <el-select
            v-model="wbConnectionKey"
            filterable
            placeholder="选择能访问 ara_fp_analyst 的连接"
            style="width: 100%"
          >
            <el-option
              v-for="conn in wbConnections"
              :key="connectionKey(conn)"
              :label="conn.label || conn.alias"
              :value="connectionKey(conn)"
            />
          </el-select>
        </el-form-item>
      </template>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submitImport">开始导入</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-tip {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.dialog-tip code {
  font-size: 11px;
}
</style>
