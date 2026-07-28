<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { listBlobCatalogConnectionsApi } from '@/api/images'
import {
  fetchFingerprintBizEvalMetaApi,
  fetchFingerprintBizEvalReportApi,
} from '@/api/fingerprints'
import { usePageDataRefresh } from '@/utils/usePageDataRefresh'
import {
  connectionKey as connectionKeyOf,
  connectionQueryParams,
  pickPreferredConnection,
} from '@/utils/dbConnection'
import { showRequestError } from '@/utils/showRequestError'

const route = useRoute()
const router = useRouter()

const loadingMeta = ref(false)
const loadingReport = ref(false)
const connections = ref([])
const connectionKey = ref('')
const datasets = ref([])
const scoreColumns = ref([])
const report = ref(null)

const filters = reactive({
  dataset_code: '',
  score_column: 'score',
})

const histCanvas = ref(null)
const fmrCanvas = ref(null)
const detCanvas = ref(null)

const selectedConnection = computed(
  () => connections.value.find((c) => connectionKeyOf(c) === connectionKey.value) || null,
)

const selectedScoreCol = computed(
  () => scoreColumns.value.find((c) => c.column === filters.score_column) || null,
)

function scoreColumnLabel(c) {
  const ready = c.metrics_ready ? '' : ' · 缺G或I'
  return `${c.label}（G${c.genuine_count}/I${c.impostor_count}${ready}）`
}

const reportTitle = computed(() => {
  const m = report.value?.meta
  if (!m) return 'Result of algorithm —'
  return `Result of algorithm ${m.score_label || m.score_column} on ${m.dataset_code}`
})

function fmtPct(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  if (n === 0) return '0%'
  if (Math.abs(n) < 0.001) return `${n.toFixed(6)}%`
  if (Math.abs(n) < 1) return `${n.toFixed(3)}%`
  return `${n.toFixed(3)}%`
}

function fmtEer(acc) {
  if (!acc || acc.eer == null) return '—'
  const ci = acc.eer_ci || []
  if (ci.length === 2 && ci[0] != null && ci[1] != null) {
    return `${fmtPct(acc.eer)} (${fmtPct(ci[0])} - ${fmtPct(ci[1])})`
  }
  return fmtPct(acc.eer)
}

let hydrating = false
let suppressDatasetWatch = false
let metaLoadSeq = 0
let reportLoadSeq = 0

async function loadConnections() {
  try {
    const res = await listBlobCatalogConnectionsApi()
    connections.value = res.data || []
    const fromQuery = String(route.query.connection || '')
    if (fromQuery && connections.value.some((c) => connectionKeyOf(c) === fromQuery)) {
      connectionKey.value = fromQuery
    } else if (!connectionKey.value) {
      const preferred = pickPreferredConnection(connections.value)
      connectionKey.value = connectionKeyOf(preferred)
    }
  } catch (err) {
    showRequestError(err, '加载数据库连接失败')
  }
}

async function loadMeta() {
  const conn = selectedConnection.value
  const params = connectionQueryParams(conn)
  if (!params) return
  const seq = ++metaLoadSeq
  loadingMeta.value = true
  try {
    const q = { ...params }
    if (filters.dataset_code) q.dataset_code = filters.dataset_code
    const res = await fetchFingerprintBizEvalMetaApi(q)
    if (seq !== metaLoadSeq) return
    const data = res.data || {}
    datasets.value = data.datasets || []
    scoreColumns.value = data.score_columns || []
    if (!filters.dataset_code && datasets.value.length) {
      const prefer = datasets.value.find((d) => d === 'PK_5W') || datasets.value[0]
      suppressDatasetWatch = true
      try {
        filters.dataset_code = prefer
      } finally {
        suppressDatasetWatch = false
      }
    }
    const cols = scoreColumns.value
    if (cols.length) {
      const stillOk = cols.some((c) => c.column === filters.score_column)
      if (!stillOk) {
        const def = cols.find((c) => c.is_default) || cols[0]
        filters.score_column = def.column
      }
    }
  } catch (err) {
    if (seq !== metaLoadSeq) return
    showRequestError(err, '加载评测元数据失败')
  } finally {
    if (seq === metaLoadSeq) loadingMeta.value = false
  }
}

async function loadReport({ quiet = false } = {}) {
  const conn = selectedConnection.value
  const params = connectionQueryParams(conn)
  if (!params) return
  if (!filters.dataset_code) {
    if (!quiet) ElMessage.warning('请选择 data_set_code')
    return
  }
  if (!filters.score_column) {
    if (!quiet) ElMessage.warning('请选择算法分数列')
    return
  }
  const seq = ++reportLoadSeq
  loadingReport.value = true
  try {
    const res = await fetchFingerprintBizEvalReportApi({
      ...params,
      dataset_code: filters.dataset_code,
      score_column: filters.score_column,
    })
    if (seq !== reportLoadSeq) return
    report.value = res.data || null
    await drawChartsWhenReady()
    scheduleChartRedraws()
  } catch (err) {
    if (seq !== reportLoadSeq) return
    // Keep last good report on transient errors (visibility / race refreshes).
    if (!quiet) showRequestError(err, '计算评测报告失败')
  } finally {
    if (seq === reportLoadSeq) loadingReport.value = false
  }
}

function syncQuery() {
  router.replace({
    name: 'fingerprint-eval',
    query: {
      connection: connectionKey.value || undefined,
      dataset_code: filters.dataset_code || undefined,
      score_column: filters.score_column || undefined,
    },
  })
}

function goBack() {
  router.push({ name: 'fingerprint-pairs' })
}

/* —— Hisign-style canvas charts —— */
function clearCanvas(canvas) {
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
}

function sizeCanvas(canvas) {
  if (!canvas) return { ctx: null, w: 0, h: 0, dpr: 1 }
  const parent = canvas.parentElement
  const cssW = Math.max(280, parent?.clientWidth || 320)
  const cssH = 240
  const dpr = window.devicePixelRatio || 1
  canvas.width = Math.round(cssW * dpr)
  canvas.height = Math.round(cssH * dpr)
  canvas.style.width = `${cssW}px`
  canvas.style.height = `${cssH}px`
  const ctx = canvas.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, cssW, cssH)
  return { ctx, w: cssW, h: cssH, dpr }
}

function drawFrame(ctx, pad, w, h) {
  ctx.strokeStyle = '#666'
  ctx.lineWidth = 1
  ctx.strokeRect(pad.l, pad.t, w - pad.l - pad.r, h - pad.t - pad.b)
}

function drawLinearTicks(ctx, pad, w, h, {
  xMin, xMax, yMin, yMax, xTicks = 5, yTicks = 5, xLabel, yLabel, fmtX, fmtY,
}) {
  const plotW = w - pad.l - pad.r
  const plotH = h - pad.t - pad.b
  const xOf = (x) => pad.l + ((x - xMin) / (xMax - xMin || 1)) * plotW
  const yOf = (y) => pad.t + plotH - ((y - yMin) / (yMax - yMin || 1)) * plotH
  ctx.fillStyle = '#444'
  ctx.font = '10px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  for (let i = 0; i <= xTicks; i++) {
    const xv = xMin + ((xMax - xMin) * i) / xTicks
    const x = xOf(xv)
    ctx.strokeStyle = '#ddd'
    ctx.beginPath()
    ctx.moveTo(x, pad.t)
    ctx.lineTo(x, h - pad.b)
    ctx.stroke()
    ctx.strokeStyle = '#666'
    ctx.beginPath()
    ctx.moveTo(x, h - pad.b)
    ctx.lineTo(x, h - pad.b + 4)
    ctx.stroke()
    ctx.fillText(fmtX ? fmtX(xv) : String(xv), x, h - pad.b + 5)
  }
  ctx.textAlign = 'right'
  ctx.textBaseline = 'middle'
  for (let i = 0; i <= yTicks; i++) {
    const yv = yMin + ((yMax - yMin) * i) / yTicks
    const y = yOf(yv)
    ctx.strokeStyle = '#eee'
    ctx.beginPath()
    ctx.moveTo(pad.l, y)
    ctx.lineTo(w - pad.r, y)
    ctx.stroke()
    ctx.strokeStyle = '#666'
    ctx.beginPath()
    ctx.moveTo(pad.l - 4, y)
    ctx.lineTo(pad.l, y)
    ctx.stroke()
    ctx.fillText(fmtY ? fmtY(yv) : String(yv), pad.l - 6, y)
  }
  ctx.textAlign = 'center'
  ctx.textBaseline = 'bottom'
  ctx.font = '11px sans-serif'
  ctx.fillText(xLabel, pad.l + plotW / 2, h - 2)
  if (yLabel) {
    ctx.save()
    ctx.translate(11, pad.t + plotH / 2)
    ctx.rotate(-Math.PI / 2)
    ctx.textBaseline = 'top'
    ctx.fillText(yLabel, 0, 0)
    ctx.restore()
  }
  return { xOf, yOf, plotW, plotH }
}

function fillUnderCurve(ctx, pts, yBase, color) {
  if (pts.length < 2) return
  ctx.beginPath()
  ctx.moveTo(pts[0][0], yBase)
  pts.forEach(([x, y]) => ctx.lineTo(x, y))
  ctx.lineTo(pts[pts.length - 1][0], yBase)
  ctx.closePath()
  ctx.fillStyle = color
  ctx.fill()
}

function strokeCurve(ctx, pts, color, width = 1.5) {
  if (pts.length < 2) return
  ctx.beginPath()
  pts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)))
  ctx.strokeStyle = color
  ctx.lineWidth = width
  ctx.stroke()
}

function drawHist() {
  const canvas = histCanvas.value
  const dist = report.value?.charts?.score_distribution
  const xs = dist?.x || dist?.bin_centers
  const gDens = dist?.genuine_density
  const iDens = dist?.impostor_density
  if (!canvas || !xs?.length || !gDens?.length || !iDens?.length) {
    clearCanvas(canvas)
    return
  }
  const { ctx, w, h } = sizeCanvas(canvas)
  if (!ctx) return
  const pad = { l: 36, r: 10, t: 28, b: 34 }
  const maxY = Math.max(1e-6, ...gDens, ...iDens) * 1.08
  drawFrame(ctx, pad, w, h)
  const { xOf, yOf } = drawLinearTicks(ctx, pad, w, h, {
    xMin: 0,
    xMax: 1,
    yMin: 0,
    yMax: maxY,
    xTicks: 5,
    yTicks: 4,
    xLabel: 'threshold',
    yLabel: '',
    fmtX: (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1)),
    fmtY: () => '',
  })

  const gPts = xs.map((x, i) => [xOf(x), yOf(gDens[i] || 0)])
  const iPts = xs.map((x, i) => [xOf(x), yOf(iDens[i] || 0)])
  const yBase = yOf(0)
  fillUnderCurve(ctx, iPts, yBase, 'rgba(220, 40, 40, 0.45)')
  fillUnderCurve(ctx, gPts, yBase, 'rgba(40, 170, 70, 0.40)')
  strokeCurve(ctx, iPts, '#c0392b', 1.2)
  strokeCurve(ctx, gPts, '#1e8449', 1.2)

  ctx.font = '11px sans-serif'
  ctx.fillStyle = '#c0392b'
  ctx.textAlign = 'left'
  ctx.fillText('Impostors', pad.l + 8, pad.t + 14)
  ctx.fillStyle = '#1e8449'
  ctx.fillText('Genuines', pad.l + 8, pad.t + 28)
}

function drawFmrFnmr() {
  const canvas = fmrCanvas.value
  const series = report.value?.charts?.fmr_fnmr
  if (!canvas || !series?.length) {
    clearCanvas(canvas)
    return
  }
  const { ctx, w, h } = sizeCanvas(canvas)
  if (!ctx) return
  const pad = { l: 42, r: 10, t: 22, b: 34 }
  drawFrame(ctx, pad, w, h)
  const { xOf, yOf } = drawLinearTicks(ctx, pad, w, h, {
    xMin: 0,
    xMax: 1,
    yMin: 0,
    yMax: 100,
    xTicks: 5,
    yTicks: 5,
    xLabel: 'threshold',
    yLabel: '',
    fmtX: (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1)),
    fmtY: (v) => `${Math.round(v)}%`,
  })

  const fmrPts = series.map((p) => [xOf(p.threshold), yOf(Math.min(100, Math.max(0, p.fmr_pct ?? p.fmr * 100)))])
  const fnmrPts = series.map((p) => [xOf(p.threshold), yOf(Math.min(100, Math.max(0, p.fnmr_pct ?? p.fnmr * 100)))])
  strokeCurve(ctx, fmrPts, '#c0392b', 1.6)
  strokeCurve(ctx, fnmrPts, '#27ae60', 1.6)

  ctx.font = '11px sans-serif'
  ctx.textAlign = 'left'
  ctx.fillStyle = '#c0392b'
  ctx.fillText('FMR', pad.l + 8, pad.t + 12)
  ctx.fillStyle = '#27ae60'
  ctx.fillText('FNMR', pad.l + 8, pad.t + 26)
}

function drawDet() {
  const canvas = detCanvas.value
  const series = report.value?.charts?.det
  const axis = report.value?.charts?.det_axis || {}
  if (!canvas || !series?.length) {
    clearCanvas(canvas)
    return
  }
  const { ctx, w, h } = sizeCanvas(canvas)
  if (!ctx) return
  const pad = { l: 48, r: 12, t: 22, b: 36 }
  const fmrMin = axis.fmr_min ?? 1e-4
  const fmrMax = axis.fmr_max ?? 1
  const fnmrMin = axis.fnmr_min ?? 1e-4
  const fnmrMax = axis.fnmr_max ?? 1
  const logX0 = Math.log10(fmrMin)
  const logX1 = Math.log10(fmrMax)
  const logY0 = Math.log10(fnmrMin)
  const logY1 = Math.log10(fnmrMax)
  const plotW = w - pad.l - pad.r
  const plotH = h - pad.t - pad.b
  const xOf = (fmr) => {
    const v = Math.min(fmrMax, Math.max(fmrMin, Math.max(fmr, fmrMin * 0.5)))
    return pad.l + ((Math.log10(v) - logX0) / (logX1 - logX0)) * plotW
  }
  const yOf = (fnmr) => {
    const v = Math.min(fnmrMax, Math.max(fnmrMin, Math.max(fnmr, fnmrMin * 0.5)))
    return pad.t + plotH - ((Math.log10(v) - logY0) / (logY1 - logY0)) * plotH
  }

  drawFrame(ctx, pad, w, h)

  // decade grid + ticks
  const decades = []
  for (let e = Math.ceil(logX0); e <= Math.floor(logX1); e++) decades.push(10 ** e)
  ctx.font = '9px sans-serif'
  ctx.fillStyle = '#444'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  decades.forEach((v) => {
    const x = xOf(v)
    ctx.strokeStyle = '#e0e0e0'
    ctx.beginPath()
    ctx.moveTo(x, pad.t)
    ctx.lineTo(x, h - pad.b)
    ctx.stroke()
    ctx.fillText(v >= 1 ? '1' : `10^${Math.round(Math.log10(v))}`, x, h - pad.b + 4)
  })
  const yDecades = []
  for (let e = Math.ceil(logY0); e <= Math.floor(logY1); e++) yDecades.push(10 ** e)
  ctx.textAlign = 'right'
  ctx.textBaseline = 'middle'
  yDecades.forEach((v) => {
    const y = yOf(v)
    ctx.strokeStyle = '#e0e0e0'
    ctx.beginPath()
    ctx.moveTo(pad.l, y)
    ctx.lineTo(w - pad.r, y)
    ctx.stroke()
    ctx.fillText(v >= 1 ? '1' : `10^${Math.round(Math.log10(v))}`, pad.l - 5, y)
  })

  // EER line (FMR = FNMR)
  ctx.setLineDash([5, 4])
  ctx.strokeStyle = '#888'
  ctx.lineWidth = 1
  ctx.beginPath()
  const eerLo = Math.max(fmrMin, fnmrMin)
  const eerHi = Math.min(fmrMax, fnmrMax)
  ctx.moveTo(xOf(eerLo), yOf(eerLo))
  ctx.lineTo(xOf(eerHi), yOf(eerHi))
  ctx.stroke()
  ctx.setLineDash([])
  ctx.fillStyle = '#555'
  ctx.font = '10px sans-serif'
  ctx.textAlign = 'left'
  const mid = Math.sqrt(eerLo * eerHi)
  ctx.fillText('EER line', xOf(mid) + 4, yOf(mid) - 6)

  // vertical refs
  const refs = [
    { fmr: 0.0001, label: 'FMR10000' },
    { fmr: 0.001, label: 'FMR1000' },
    { fmr: 0.01, label: 'FMR100' },
  ]
  ctx.font = '9px sans-serif'
  refs.forEach(({ fmr, label }) => {
    if (fmr < fmrMin || fmr > fmrMax) return
    const x = xOf(fmr)
    ctx.strokeStyle = '#aaa'
    ctx.setLineDash([3, 3])
    ctx.beginPath()
    ctx.moveTo(x, pad.t)
    ctx.lineTo(x, h - pad.b)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.save()
    ctx.translate(x + 3, pad.t + 4)
    ctx.rotate(-Math.PI / 2)
    ctx.textAlign = 'right'
    ctx.textBaseline = 'top'
    ctx.fillStyle = '#666'
    ctx.fillText(label, 0, 0)
    ctx.restore()
  })

  // stepped DET curve
  const pts = series
    .map((p) => [xOf(Math.max(p.fmr, fmrMin * 0.999)), yOf(Math.max(p.fnmr, fnmrMin * 0.999))])
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y))
  strokeCurve(ctx, pts, '#1a5276', 1.8)

  ctx.fillStyle = '#444'
  ctx.font = '11px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'bottom'
  ctx.fillText('FMR', pad.l + plotW / 2, h - 2)
  ctx.save()
  ctx.translate(12, pad.t + plotH / 2)
  ctx.rotate(-Math.PI / 2)
  ctx.textBaseline = 'top'
  ctx.fillText('FNMR', 0, 0)
  ctx.restore()
}

function drawCharts() {
  drawHist()
  drawFmrFnmr()
  drawDet()
}

function canvasLayoutReady() {
  const el = histCanvas.value
  if (!el || !fmrCanvas.value || !detCanvas.value) return false
  // Router fade-slide leaves 0-width parents on first paint; wait for real layout.
  return (el.parentElement?.clientWidth || 0) > 40
}

async function drawChartsWhenReady(tries = 24) {
  await nextTick()
  if (canvasLayoutReady()) {
    drawCharts()
    return
  }
  if (tries <= 0 || !report.value) return
  await new Promise((resolve) => setTimeout(resolve, 50))
  await drawChartsWhenReady(tries - 1)
}

/** Extra redraws after route transition (~150ms) settles. */
function scheduleChartRedraws() {
  for (const delay of [180, 400, 900]) {
    setTimeout(() => {
      if (report.value && canvasLayoutReady()) drawCharts()
    }, delay)
  }
}

function onResize() {
  if (report.value) drawCharts()
}

watch(connectionKey, async () => {
  if (hydrating) return
  await loadMeta()
  if (filters.dataset_code && filters.score_column) {
    await loadReport({ quiet: true })
  }
  syncQuery()
})

watch(
  () => filters.dataset_code,
  async () => {
    if (hydrating || suppressDatasetWatch) return
    await loadMeta()
    if (filters.dataset_code && filters.score_column) {
      await loadReport({ quiet: true })
    }
    syncQuery()
  },
)

watch(
  () => filters.score_column,
  async () => {
    if (hydrating || suppressDatasetWatch) return
    if (filters.dataset_code && filters.score_column) {
      await loadReport({ quiet: true })
    }
    syncQuery()
  },
)

let evalBootstrapped = false

async function refreshEvalPage() {
  if (!evalBootstrapped) {
    hydrating = true
    try {
      if (!filters.dataset_code) {
        filters.dataset_code = String(route.query.dataset_code || '')
      }
      if (!filters.score_column) {
        filters.score_column = String(route.query.score_column || 'score')
      }
      await loadConnections()
      await loadMeta()
      if (filters.dataset_code) {
        await loadMeta()
      }
      if (filters.dataset_code && filters.score_column) {
        await loadReport({ quiet: true })
      }
      syncQuery()
    } finally {
      hydrating = false
      evalBootstrapped = true
    }
    return
  }
  if (!connections.value.length || !connectionKey.value) {
    await loadConnections()
  }
  await loadMeta()
  if (filters.dataset_code && filters.score_column) {
    await loadReport({ quiet: true })
  }
}

usePageDataRefresh(refreshEvalPage, {
  // Retry while connections/meta missing, or filters ready but report not yet loaded.
  isEmpty: () => {
    if (!connections.value.length) return true
    if (!datasets.value.length) return true
    // Meta settled with no score columns — stop polling (not a transient race).
    if (!scoreColumns.value.length) return false
    if (filters.dataset_code && filters.score_column) return !report.value
    return false
  },
  alwaysRefreshOnVisible: false,
  intervalMs: 1500,
  maxEmptyRetries: 12,
  mountRetryDelaysMs: [200, 600, 1500, 3000],
})

onMounted(() => {
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="eval-page">
    <div class="eval-toolbar">
      <div class="eval-title">
        <h2>指纹评测指标</h2>
        <p>
          按 data_set_code + 分数列（score / NeuNTms / …）计算 EER、FMR、DET；
          sameflag：1=Genuine，0=Impostor
        </p>
      </div>
      <div class="eval-actions">
        <el-button @click="goBack">返回指纹浏览</el-button>
        <el-select
          v-model="connectionKey"
          filterable
          placeholder="业务库连接"
          style="width: 220px"
        >
          <el-option
            v-for="conn in connections"
            :key="connectionKeyOf(conn)"
            :label="conn.label || conn.alias"
            :value="connectionKeyOf(conn)"
          />
        </el-select>
        <el-select
          v-model="filters.dataset_code"
          filterable
          clearable
          placeholder="data_set_code"
          style="width: 160px"
          :loading="loadingMeta"
        >
          <el-option v-for="d in datasets" :key="d" :label="d" :value="d" />
        </el-select>
        <el-select
          v-model="filters.score_column"
          filterable
          placeholder="算法分数列"
          style="width: 220px"
          :loading="loadingMeta"
        >
          <el-option
            v-for="c in scoreColumns"
            :key="c.column"
            :label="scoreColumnLabel(c)"
            :value="c.column"
          />
        </el-select>
        <el-button type="primary" :loading="loadingReport" @click="loadReport(); syncQuery()">
          生成报告
        </el-button>
      </div>
    </div>

    <p v-if="!loadingMeta && scoreColumns.length === 0" class="hint-warn">
      当前连接/数据集下未扫到有数值的分数列（score、NeuNTms、Bionems、BioIdms、HXms、AlgVersion）。
    </p>
    <p
      v-else-if="selectedScoreCol && selectedScoreCol.metrics_ready === false"
      class="hint-warn"
    >
      当前列 Genuine={{ selectedScoreCol.genuine_count }}、Impostor={{ selectedScoreCol.impostor_count }}；
      完整 EER/FMR 需要两边都有样本（sameflag=0 与 1）。
    </p>

    <el-empty
      v-if="!report && !loadingReport"
      description="选择数据集与分数列后生成报告（无注册/内存数据的指标已跳过）"
    />

    <div v-if="report" class="eval-report" v-loading="loadingReport">
      <h3 class="report-h">{{ reportTitle }}</h3>

      <div class="section-head">Accuracy indicators</div>
      <table class="metric-table">
        <thead>
          <tr>
            <th>EER</th>
            <th>FMR<sub>100</sub></th>
            <th>FMR<sub>1000</sub></th>
            <th>FMR<sub>10000</sub></th>
            <th>ZeroFMR</th>
            <th>ZeroFNMR</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{{ fmtEer(report.accuracy) }}</td>
            <td>{{ fmtPct(report.accuracy.fmr100) }}</td>
            <td>{{ fmtPct(report.accuracy.fmr1000) }}</td>
            <td>{{ fmtPct(report.accuracy.fmr10000) }}</td>
            <td>{{ fmtPct(report.accuracy.zero_fmr) }}</td>
            <td>{{ fmtPct(report.accuracy.zero_fnmr) }}</td>
          </tr>
        </tbody>
      </table>
      <p class="count-note">
        Genuine={{ report.counts.genuine }} · Impostor={{ report.counts.impostor }} ·
        接受规则：score ≥ threshold · EER 阈值 ≈ {{ report.accuracy.eer_threshold }}
      </p>

      <div class="section-head">Graphs</div>
      <div class="charts-row">
        <div class="chart-box">
          <div class="chart-title">Score distributions</div>
          <canvas ref="histCanvas" />
        </div>
        <div class="chart-box">
          <div class="chart-title">FMR(t) and FNMR(t) graphs</div>
          <canvas ref="fmrCanvas" />
        </div>
        <div class="chart-box">
          <div class="chart-title">DET graph</div>
          <canvas ref="detCanvas" />
        </div>
      </div>

      <div class="section-head">
        Description of algorithm {{ report.meta.score_label || report.meta.score_column }}
      </div>
      <p class="desc-body">
        数据源表 {{ report.meta.match_table }}；分数列
        <code>{{ report.meta.score_column }}</code>；数据集
        <code>{{ report.meta.dataset_code }}</code>。
        未计算：REJ*、注册耗时、模板大小、内存（表中无对应采集字段）。
      </p>
    </div>
  </div>
</template>

<style scoped>
.eval-page {
  padding: 16px 20px 32px;
  max-width: 1200px;
  margin: 0 auto;
}
.eval-toolbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
.eval-title h2 {
  margin: 0 0 4px;
  font-size: 1.25rem;
}
.eval-title p {
  margin: 0;
  color: #666;
  font-size: 13px;
}
.eval-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.hint-warn {
  margin: 0 0 12px;
  font-size: 13px;
  color: #b26a00;
  background: #fff8e6;
  border: 1px solid #f0d9a0;
  padding: 8px 10px;
  border-radius: 4px;
}
.report-h {
  margin: 0 0 12px;
  color: #1a3a6b;
  font-size: 1.15rem;
  border-bottom: 2px solid #2c5aa0;
  padding-bottom: 6px;
}
.section-head {
  background: #f5e8c7;
  color: #333;
  font-weight: 600;
  padding: 6px 10px;
  margin: 14px 0 0;
  border: 1px solid #d4c4a0;
}
.metric-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.metric-table th {
  background: #1a3a6b;
  color: #fff;
  padding: 8px 10px;
  text-align: center;
  font-weight: 600;
}
.metric-table td {
  border: 1px solid #ccc;
  padding: 8px 10px;
  text-align: center;
  background: #fff;
}
.count-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: #666;
}
.charts-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  border: 1px solid #d4c4a0;
  border-top: none;
  padding: 10px 8px 12px;
  background: #fff;
}
.chart-box {
  min-width: 0;
  border: 1px solid #e5e5e5;
  padding: 4px 2px 2px;
  background: #fff;
}
.chart-title {
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 2px;
  color: #222;
}
.desc-body {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid #d4c4a0;
  border-top: none;
  font-size: 13px;
  color: #444;
  background: #fff;
}
@media (max-width: 900px) {
  .charts-row {
    grid-template-columns: 1fr;
  }
}
</style>
