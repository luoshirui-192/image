<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchImageBlob } from '@/api/images'
import {
  cancelFingerprintImportJobApi,
  deleteFingerprintPairApi,
  fetchFingerprintCompareApi,
  fetchFingerprintImportJobApi,
  fetchFingerprintMetaApi,
  fetchFingerprintPairsApi,
  importFingerprintZipApi,
} from '@/api/fingerprints'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const compareLoading = ref(false)
const importing = ref(false)
const importJob = ref(null)
const pollTimer = ref(null)
const rows = ref([])
const total = ref(0)
const selectedPairId = ref(null)
const treeRef = ref(null)

const meta = reactive({
  finger_positions: [],
  algo_versions: [],
  layer_types: [],
})

const filters = reactive({
  keyword: '',
  finger_position: '',
  batch_name: '',
  layer_type: '',
  algo_version: '',
  score_min: undefined,
  score_max: undefined,
})

const payload = ref(null)
const showLabels = ref(true)
const zoom = ref(1)
const leftTypes = ref([])
const rightTypes = ref([])
const selectedVersions = ref([])
const layersReady = ref(false)

const leftUrl = ref('')
const rightUrl = ref('')
const leftCanvas = ref(null)
const rightCanvas = ref(null)
const leftImg = ref(null)
const rightImg = ref(null)

const layerTypeLabel = computed(() => {
  const map = {}
  for (const item of meta.layer_types) {
    map[item.layer_key] = item.label || item.layer_key
  }
  return map
})

const checkboxOptions = computed(() => {
  const available = new Set(payload.value?.available_layer_types || [])
  const opts = (payload.value?.layer_type_options || []).filter((t) => available.has(t.layer_key))
  if (opts.length) return opts
  return [...available].map((key) => ({
    layer_key: key,
    label: layerTypeLabel.value[key] || key,
    color: '#888',
  }))
})

const availableVersions = computed(() => payload.value?.available_algo_versions || [])

const selectedPair = computed(() => rows.value.find((r) => r.id === selectedPairId.value) || null)

/** Left tree: group pairs by finger_position (blob-browse style). */
const treeData = computed(() => {
  const groups = new Map()
  for (const row of rows.value) {
    const key = row.finger_position || 'unknown'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(row)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([position, items]) => ({
      id: `pos:${position}`,
      label: `${position}（${items.length}）`,
      isGroup: true,
      children: items.map((row) => ({
        id: `pair:${row.id}`,
        pairId: row.id,
        label: formatPairLabel(row),
        isGroup: false,
        row,
      })),
    }))
})

function formatPairLabel(row) {
  const score = row.match_score != null ? ` · ${row.match_score}` : ''
  return `${row.batch_name || `#${row.id}`}${score}`
}

async function loadMeta() {
  const res = await fetchFingerprintMetaApi()
  meta.finger_positions = res.data.finger_positions || []
  meta.algo_versions = res.data.algo_versions || []
  meta.layer_types = res.data.layer_types || []
}

async function loadPairs() {
  loading.value = true
  try {
    const params = {
      page: 1,
      page_size: 500,
    }
    for (const key of ['keyword', 'finger_position', 'batch_name', 'layer_type', 'algo_version']) {
      if (filters[key]) params[key] = filters[key]
    }
    if (filters.score_min != null && filters.score_min !== '') params.score_min = filters.score_min
    if (filters.score_max != null && filters.score_max !== '') params.score_max = filters.score_max
    const res = await fetchFingerprintPairsApi(params)
    rows.value = res.data.items || []
    total.value = res.data.total || 0

    if (selectedPairId.value && !rows.value.some((r) => r.id === selectedPairId.value)) {
      selectedPairId.value = null
      clearCompare()
    }
  } catch (err) {
    ElMessage.error(err.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  loadPairs()
}

function onReset() {
  filters.keyword = ''
  filters.finger_position = ''
  filters.batch_name = ''
  filters.layer_type = ''
  filters.algo_version = ''
  filters.score_min = undefined
  filters.score_max = undefined
  loadPairs()
}

function onTreeNodeClick(data) {
  if (data.isGroup || !data.pairId) return
  selectPair(data.pairId)
}

function selectPair(pairId) {
  selectedPairId.value = Number(pairId)
  router.replace({ query: { ...route.query, id: String(pairId) } }).catch(() => {})
  loadCompare(Number(pairId))
}

function clearCompare() {
  payload.value = null
  layersReady.value = false
  leftTypes.value = []
  rightTypes.value = []
  selectedVersions.value = []
  revokeUrls()
  leftImg.value = null
  rightImg.value = null
}

async function onDeleteSelected() {
  const row = selectedPair.value
  if (!row) return
  try {
    await ElMessageBox.confirm(`确认删除配对 ${row.batch_name}？`, '删除确认', { type: 'warning' })
    await deleteFingerprintPairApi(row.id)
    ElMessage.success('已删除')
    selectedPairId.value = null
    clearCompare()
    await loadPairs()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '删除失败')
  }
}

function stopPoll() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

async function pollImportJob(jobId) {
  if (jobId == null) {
    stopPoll()
    importing.value = false
    ElMessage.error('导入任务 ID 无效')
    return
  }
  try {
    const res = await fetchFingerprintImportJobApi(jobId)
    const job = res?.data
    if (!job || typeof job !== 'object') {
      stopPoll()
      importing.value = false
      ElMessage.error('导入进度接口返回异常')
      return
    }
    importJob.value = job
    const status = job.status
    if (status === 'completed' || status === 'failed' || status === 'cancelled') {
      stopPoll()
      importing.value = false
      if (status === 'completed') ElMessage.success(job.message || '导入完成')
      else if (status === 'failed') ElMessage.error(job.message || job.last_error || '导入失败')
      else ElMessage.warning(job.message || '已取消')
      await loadMeta()
      await loadPairs()
    }
  } catch (err) {
    stopPoll()
    importing.value = false
    ElMessage.error(err.message || '查询导入进度失败')
  }
}

async function onZipChange(uploadFile) {
  const file = uploadFile.raw
  if (!file) return
  importing.value = true
  importJob.value = null
  stopPoll()
  try {
    const res = await importFingerprintZipApi(file, { algo_version: '1.0', skip_existing: true })
    const job = res?.data?.job
    if (!job?.id) {
      importing.value = false
      ElMessage.error('未拿到导入任务，请确认后端已更新')
      return
    }
    importJob.value = job
    ElMessage.success('导入任务已启动')
    await pollImportJob(job.id)
    if (importing.value) {
      pollTimer.value = setInterval(() => pollImportJob(job.id), 1500)
    }
  } catch (err) {
    importing.value = false
    ElMessage.error(err.message || '导入失败')
  }
}

async function onCancelImport() {
  if (!importJob.value?.id) return
  try {
    await cancelFingerprintImportJobApi(importJob.value.id)
    ElMessage.info('已请求取消')
  } catch (err) {
    ElMessage.error(err.message || '取消失败')
  }
}

function revokeUrls() {
  if (leftUrl.value) URL.revokeObjectURL(leftUrl.value)
  if (rightUrl.value) URL.revokeObjectURL(rightUrl.value)
  leftUrl.value = ''
  rightUrl.value = ''
}

async function loadCompare(pairId) {
  if (!pairId) return
  compareLoading.value = true
  layersReady.value = false
  try {
    const res = await fetchFingerprintCompareApi(pairId, { show_labels: '1' })
    payload.value = res.data
    leftTypes.value = [...(res.data.available_layer_types || [])]
    rightTypes.value = [...(res.data.available_layer_types || [])]
    selectedVersions.value = [...(res.data.available_algo_versions || [])]
    layersReady.value = true

    revokeUrls()
    const leftBlob = await fetchImageBlob(res.data.left.image_path, {
      id: res.data.left.image_id,
      thumb: false,
    })
    const rightBlob = await fetchImageBlob(res.data.right.image_path, {
      id: res.data.right.image_id,
      thumb: false,
    })
    leftUrl.value = URL.createObjectURL(leftBlob)
    rightUrl.value = URL.createObjectURL(rightBlob)
    await nextTick()
    await drawBoth()
  } catch (err) {
    clearCompare()
    ElMessage.error(err.message || '加载对比失败')
  } finally {
    compareLoading.value = false
  }
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = url
  })
}

function layerVisible(layer, side) {
  const types = side === 'left' ? leftTypes.value : rightTypes.value
  if (!types.includes(layer.layer_type)) return false
  if (selectedVersions.value.length && !selectedVersions.value.includes(layer.algo_version)) {
    return false
  }
  return true
}

function drawSide(canvasEl, imgEl, side) {
  if (!canvasEl || !imgEl || !payload.value) return
  const layers = (payload.value.layers || []).filter(
    (l) => l.side === side && layerVisible(l, side),
  )
  const width = imgEl.naturalWidth || imgEl.width
  const height = imgEl.naturalHeight || imgEl.height
  const scale = zoom.value
  canvasEl.width = Math.round(width * scale)
  canvasEl.height = Math.round(height * scale)
  const ctx = canvasEl.getContext('2d')
  ctx.clearRect(0, 0, canvasEl.width, canvasEl.height)
  ctx.imageSmoothingEnabled = false
  ctx.drawImage(imgEl, 0, 0, canvasEl.width, canvasEl.height)

  const arrowLen = 12 * scale
  for (const layer of layers) {
    const color = layer.color || '#e53935'
    const minutiae = layer.minutiae?.minutiae || []
    for (const m of minutiae) {
      const x = m.x * scale
      const y = m.y * scale
      const rad = ((m.d || 0) * Math.PI) / 180
      ctx.beginPath()
      ctx.arc(x, y, 2.2 * scale, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.lineTo(x + Math.cos(rad) * arrowLen, y - Math.sin(rad) * arrowLen)
      ctx.strokeStyle = color
      ctx.lineWidth = Math.max(1, scale)
      ctx.stroke()
      if (showLabels.value && m.index != null) {
        ctx.fillStyle = '#111'
        ctx.font = `${Math.max(9, 10 * scale)}px sans-serif`
        ctx.fillText(String(m.index), x + 3 * scale, y - 3 * scale)
      }
    }
  }
}

async function drawBoth() {
  if (!leftUrl.value || !rightUrl.value) return
  leftImg.value = await loadImage(leftUrl.value)
  rightImg.value = await loadImage(rightUrl.value)
  redrawBoth()
}

function redrawBoth() {
  if (leftImg.value) drawSide(leftCanvas.value, leftImg.value, 'left')
  if (rightImg.value) drawSide(rightCanvas.value, rightImg.value, 'right')
}

watch([leftTypes, rightTypes, selectedVersions, showLabels, zoom], () => {
  if (!layersReady.value) return
  redrawBoth()
})

onMounted(async () => {
  await loadMeta()
  await loadPairs()
  const qid = Number(route.query.id || route.params.id)
  if (qid) {
    selectedPairId.value = qid
    await loadCompare(qid)
  }
})

onBeforeUnmount(() => {
  stopPoll()
  revokeUrls()
})
</script>

<template>
  <div class="fp-page">
    <div class="fp-toolbar">
      <div class="fp-title">
        <h2>指纹成对对比</h2>
        <p>左侧筛选/选择配对，右侧即时对比（无需跳转）</p>
      </div>
      <div class="import-actions">
        <el-upload
          :show-file-list="false"
          accept=".zip"
          :disabled="importing"
          :auto-upload="false"
          :on-change="onZipChange"
        >
          <el-button type="primary" :loading="importing">导入整包 zip</el-button>
        </el-upload>
        <el-button v-if="importing && importJob" @click="onCancelImport">取消导入</el-button>
      </div>
    </div>

    <el-card v-if="importJob" shadow="never" class="import-progress">
      <div class="import-progress-head">
        <strong>{{ importJob.zip_name || '导入任务' }}</strong>
        <span>{{ importJob.status }} · {{ importJob.message }}</span>
      </div>
      <el-progress
        :percentage="Number(importJob.percent || 0)"
        :status="importJob.status === 'failed' ? 'exception' : (importJob.status === 'completed' ? 'success' : undefined)"
      />
      <div class="import-progress-meta">
        进度 {{ importJob.processed || 0 }}/{{ importJob.total_estimate || '?' }}
        · 成功 {{ importJob.succeeded || 0 }}
        · 跳过 {{ importJob.skipped || 0 }}
        · 失败 {{ importJob.failed || 0 }}
      </div>
    </el-card>

    <div class="layout">
      <aside class="tree-panel" v-loading="loading">
        <div class="panel-head">
          <strong>配对目录</strong>
          <span class="muted">共 {{ total }} 对</span>
        </div>

        <div class="filter-box">
          <el-input
            v-model="filters.keyword"
            clearable
            size="small"
            placeholder="关键词"
            @keyup.enter="onSearch"
          />
          <el-select
            v-model="filters.finger_position"
            clearable
            size="small"
            placeholder="指位"
            style="width: 100%"
          >
            <el-option v-for="p in meta.finger_positions" :key="p" :label="p" :value="p" />
          </el-select>
          <el-select
            v-model="filters.layer_type"
            clearable
            size="small"
            placeholder="特征层"
            style="width: 100%"
          >
            <el-option
              v-for="t in meta.layer_types"
              :key="t.layer_key"
              :label="t.label"
              :value="t.layer_key"
            />
          </el-select>
          <div class="score-row">
            <el-input-number
              v-model="filters.score_min"
              :controls="false"
              size="small"
              placeholder="分min"
              style="width: 100%"
            />
            <span>~</span>
            <el-input-number
              v-model="filters.score_max"
              :controls="false"
              size="small"
              placeholder="分max"
              style="width: 100%"
            />
          </div>
          <div class="filter-actions">
            <el-button type="primary" size="small" @click="onSearch">筛选</el-button>
            <el-button size="small" @click="onReset">重置</el-button>
          </div>
        </div>

        <div class="tree-wrap">
          <el-tree
            v-if="treeData.length"
            ref="treeRef"
            :data="treeData"
            node-key="id"
            default-expand-all
            highlight-current
            :expand-on-click-node="false"
            @node-click="onTreeNodeClick"
          />
          <el-empty v-else description="暂无配对，请先导入 zip" :image-size="64" />
        </div>

        <div v-if="selectedPair" class="selection-foot">
          <div class="sel-title">{{ selectedPair.batch_name }}</div>
          <div class="sel-meta">
            {{ selectedPair.finger_position }}
            <template v-if="selectedPair.match_score != null"> · score {{ selectedPair.match_score }}</template>
          </div>
          <el-button size="small" type="danger" plain @click="onDeleteSelected">删除此配对</el-button>
        </div>
      </aside>

      <main class="compare-panel" v-loading="compareLoading">
        <template v-if="payload">
          <div class="compare-toolbar">
            <div class="meta">
              {{ payload.pair.batch_name }} · {{ payload.pair.finger_position }}
              <template v-if="payload.pair.match_score != null"> · score {{ payload.pair.match_score }}</template>
            </div>
            <div class="controls">
              <span class="label">版本</span>
              <el-checkbox-group v-model="selectedVersions">
                <el-checkbox
                  v-for="v in availableVersions"
                  :key="v"
                  :label="v"
                  :value="v"
                >{{ v }}</el-checkbox>
              </el-checkbox-group>
              <el-checkbox v-model="showLabels">编号</el-checkbox>
              <span class="label">缩放</span>
              <el-slider v-model="zoom" :min="0.5" :max="3" :step="0.1" style="width: 120px" />
            </div>
          </div>

          <div class="compare-grid">
            <div class="pane">
              <div class="pane-title">{{ payload.left.image_name }}</div>
              <div class="canvas-wrap">
                <canvas ref="leftCanvas" />
              </div>
              <div class="pane-layers">
                <span class="label">本侧特征层</span>
                <el-checkbox-group v-model="leftTypes">
                  <el-checkbox
                    v-for="opt in checkboxOptions"
                    :key="`L-${opt.layer_key}`"
                    :label="opt.layer_key"
                    :value="opt.layer_key"
                  >
                    <span class="swatch" :style="{ background: opt.color }" />
                    {{ opt.label || opt.layer_key }}
                  </el-checkbox>
                </el-checkbox-group>
              </div>
            </div>

            <div class="pane">
              <div class="pane-title">{{ payload.right.image_name }}</div>
              <div class="canvas-wrap">
                <canvas ref="rightCanvas" />
              </div>
              <div class="pane-layers">
                <span class="label">本侧特征层</span>
                <el-checkbox-group v-model="rightTypes">
                  <el-checkbox
                    v-for="opt in checkboxOptions"
                    :key="`R-${opt.layer_key}`"
                    :label="opt.layer_key"
                    :value="opt.layer_key"
                  >
                    <span class="swatch" :style="{ background: opt.color }" />
                    {{ opt.label || opt.layer_key }}
                  </el-checkbox>
                </el-checkbox-group>
              </div>
            </div>
          </div>
        </template>
        <el-empty v-else description="请在左侧树中选择一对指纹" />
      </main>
    </div>
  </div>
</template>

<style scoped>
.fp-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 120px);
  min-height: 520px;
}
.fp-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-shrink: 0;
}
.fp-title h2 {
  margin: 0 0 4px;
  font-size: 20px;
}
.fp-title p {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.import-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.import-progress {
  flex-shrink: 0;
}
.import-progress-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
}
.import-progress-meta {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 12px;
  flex: 1;
  min-height: 0;
}
.tree-panel,
.compare-panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color);
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.filter-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.score-row {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 6px;
  align-items: center;
}
.filter-actions {
  display: flex;
  gap: 8px;
}
.tree-wrap {
  flex: 1;
  overflow: auto;
  padding: 8px 4px;
}
.selection-foot {
  padding: 10px 12px;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sel-title {
  font-size: 13px;
  font-weight: 600;
  word-break: break-all;
}
.sel-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.compare-panel {
  padding: 0;
}
.compare-toolbar {
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}
.meta {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
}
.label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  flex: 1;
  min-height: 0;
}
.pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--el-border-color-lighter);
  background: #f7f7f7;
}
.pane:last-child {
  border-right: none;
}
.pane-title {
  padding: 8px 12px;
  font-size: 12px;
  background: #fff;
  border-bottom: 1px solid var(--el-border-color-lighter);
  word-break: break-all;
  flex-shrink: 0;
}
.canvas-wrap {
  flex: 1;
  overflow: auto;
  padding: 8px;
  text-align: center;
  min-height: 0;
}
.pane-layers {
  flex-shrink: 0;
  padding: 8px 12px;
  background: #fff;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
}
canvas {
  max-width: none;
  background: #fff;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.06);
}
@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .compare-grid {
    grid-template-columns: 1fr;
  }
  .pane {
    border-right: none;
    border-bottom: 1px solid var(--el-border-color-lighter);
  }
}
</style>
