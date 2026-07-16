<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchImageBlob } from '@/api/images'
import { fetchFingerprintCompareApi } from '@/api/fingerprints'

const props = defineProps({
  id: { type: [String, Number], required: false },
})

const route = useRoute()
const router = useRouter()
const pairId = computed(() => Number(props.id || route.params.id))

const loading = ref(false)
const payload = ref(null)
const showLabels = ref(true)
const zoom = ref(1)
const selectedTypes = ref([])
const selectedVersions = ref([])
const filtersReady = ref(false)
const suppressWatch = ref(false)

const leftUrl = ref('')
const rightUrl = ref('')
const leftCanvas = ref(null)
const rightCanvas = ref(null)
const leftImg = ref(null)
const rightImg = ref(null)

const typeOptions = computed(() => payload.value?.layer_type_options || [])
const availableTypes = computed(() => payload.value?.available_layer_types || [])
const availableVersions = computed(() => payload.value?.available_algo_versions || [])

const checkboxOptions = computed(() => {
  const available = new Set(availableTypes.value)
  const opts = typeOptions.value.filter((t) => available.has(t.layer_key))
  if (opts.length) return opts
  return availableTypes.value.map((key) => ({ layer_key: key, label: key, color: '#888' }))
})

function revokeUrls() {
  if (leftUrl.value) URL.revokeObjectURL(leftUrl.value)
  if (rightUrl.value) URL.revokeObjectURL(rightUrl.value)
  leftUrl.value = ''
  rightUrl.value = ''
}

async function loadCompare() {
  if (!pairId.value) return
  loading.value = true
  try {
    const params = {
      show_labels: showLabels.value ? '1' : '0',
    }
    if (filtersReady.value) {
      params.layers = selectedTypes.value.join(',')
      params.versions = selectedVersions.value.join(',')
    }
    const res = await fetchFingerprintCompareApi(pairId.value, params)
    payload.value = res.data

    if (!filtersReady.value) {
      suppressWatch.value = true
      selectedTypes.value = [...(res.data.available_layer_types || [])]
      selectedVersions.value = [...(res.data.available_algo_versions || [])]
      filtersReady.value = true
      await nextTick()
      suppressWatch.value = false
    }

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
    ElMessage.error(err.message || '加载对比失败')
  } finally {
    loading.value = false
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

function drawSide(canvasEl, imgEl, side) {
  if (!canvasEl || !imgEl || !payload.value) return
  const layers = (payload.value.layers || []).filter((l) => l.side === side)
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
  drawSide(leftCanvas.value, leftImg.value, 'left')
  drawSide(rightCanvas.value, rightImg.value, 'right')
}

watch([selectedTypes, selectedVersions, showLabels], () => {
  if (suppressWatch.value || !filtersReady.value) return
  loadCompare()
})

watch(zoom, () => {
  if (leftImg.value && rightImg.value) {
    drawSide(leftCanvas.value, leftImg.value, 'left')
    drawSide(rightCanvas.value, rightImg.value, 'right')
  }
})

onMounted(loadCompare)
onBeforeUnmount(revokeUrls)

function goBack() {
  router.push({ name: 'fingerprint-pairs' })
}
</script>

<template>
  <div v-loading="loading" class="compare-page">
    <div class="compare-toolbar">
      <div>
        <el-button @click="goBack">返回列表</el-button>
        <span v-if="payload" class="meta">
          {{ payload.pair.batch_name }} · {{ payload.pair.finger_position }}
          <template v-if="payload.pair.match_score != null"> · score {{ payload.pair.match_score }}</template>
        </span>
      </div>
      <div class="controls">
        <span class="label">特征层</span>
        <el-checkbox-group v-model="selectedTypes">
          <el-checkbox
            v-for="opt in checkboxOptions"
            :key="opt.layer_key"
            :label="opt.layer_key"
            :value="opt.layer_key"
          >
            <span class="swatch" :style="{ background: opt.color }" />
            {{ opt.label || opt.layer_key }}
          </el-checkbox>
        </el-checkbox-group>
        <span class="label">版本</span>
        <el-checkbox-group v-model="selectedVersions">
          <el-checkbox v-for="v in availableVersions" :key="v" :label="v" :value="v">{{ v }}</el-checkbox>
        </el-checkbox-group>
        <el-checkbox v-model="showLabels">编号</el-checkbox>
        <span class="label">缩放</span>
        <el-slider v-model="zoom" :min="0.5" :max="3" :step="0.1" style="width: 140px" />
      </div>
    </div>

    <div v-if="payload" class="compare-grid">
      <div class="pane">
        <div class="pane-title">{{ payload.left.image_name }}</div>
        <div class="canvas-wrap">
          <canvas ref="leftCanvas" />
        </div>
      </div>
      <div class="pane">
        <div class="pane-title">{{ payload.right.image_name }}</div>
        <div class="canvas-wrap">
          <canvas ref="rightCanvas" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.compare-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 60vh;
}
.compare-toolbar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.meta {
  margin-left: 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
}
.label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
}
.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.pane {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  background: #f7f7f7;
}
.pane-title {
  padding: 8px 12px;
  font-size: 13px;
  background: #fff;
  border-bottom: 1px solid var(--el-border-color-lighter);
  word-break: break-all;
}
.canvas-wrap {
  overflow: auto;
  max-height: calc(100vh - 260px);
  padding: 8px;
  text-align: center;
}
canvas {
  max-width: none;
  background: #fff;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.06);
}
@media (max-width: 960px) {
  .compare-grid {
    grid-template-columns: 1fr;
  }
}
</style>
