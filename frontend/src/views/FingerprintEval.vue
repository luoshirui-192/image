<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { listBlobCatalogConnectionsApi } from '@/api/images'
import {
  fetchFingerprintBizEvalMetaApi,
  fetchFingerprintBizEvalReportApi,
} from '@/api/fingerprints'

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

function connectionKeyOf(conn) {
  if (!conn) return ''
  if (conn.connection_id != null) return `ext:${conn.connection_id}`
  return `alias:${conn.alias || 'default'}`
}

function connectionQueryParams(conn) {
  if (!conn) return null
  const params = { database: 'ara_fp_analyst' }
  if (conn.connection_id != null) {
    params.connection_id = conn.connection_id
  } else {
    params.db_alias = conn.alias || 'default'
    if (!conn.connection_id && (conn.alias === 'default' || !conn.alias)) {
      params.database = ''
    }
  }
  return params
}

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

async function loadConnections() {
  try {
    const res = await listBlobCatalogConnectionsApi()
    connections.value = res.data || []
    const fromQuery = String(route.query.connection || '')
    if (fromQuery && connections.value.some((c) => connectionKeyOf(c) === fromQuery)) {
      connectionKey.value = fromQuery
    } else {
      const preferred = connections.value.find((c) =>
        String(c.label || c.alias || '').toLowerCase().includes('ara'),
      )
      connectionKey.value = connectionKeyOf(preferred || connections.value[0])
    }
  } catch (err) {
    ElMessage.error(err.message || '加载数据库连接失败')
  }
}

async function loadMeta() {
  const conn = selectedConnection.value
  const params = connectionQueryParams(conn)
  if (!params) return
  loadingMeta.value = true
  try {
    const q = { ...params }
    if (filters.dataset_code) q.dataset_code = filters.dataset_code
    const res = await fetchFingerprintBizEvalMetaApi(q)
    const data = res.data || {}
    datasets.value = data.datasets || []
    scoreColumns.value = data.score_columns || []
    if (!filters.dataset_code && datasets.value.length) {
      const prefer = datasets.value.find((d) => d === 'PK_5W') || datasets.value[0]
      filters.dataset_code = prefer
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
    datasets.value = []
    scoreColumns.value = []
    ElMessage.error(err.message || '加载评测元数据失败')
  } finally {
    loadingMeta.value = false
  }
}

async function loadReport() {
  const conn = selectedConnection.value
  const params = connectionQueryParams(conn)
  if (!params) return
  if (!filters.dataset_code) {
    ElMessage.warning('请选择 data_set_code')
    return
  }
  if (!filters.score_column) {
    ElMessage.warning('请选择算法分数列')
    return
  }
  loadingReport.value = true
  report.value = null
  try {
    const res = await fetchFingerprintBizEvalReportApi({
      ...params,
      dataset_code: filters.dataset_code,
      score_column: filters.score_column,
    })
    report.value = res.data || null
    await nextTick()
    drawCharts()
  } catch (err) {
    ElMessage.error(err.message || '计算评测报告失败')
  } finally {
    loadingReport.value = false
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

/* —— canvas charts —— */
function clearCanvas(canvas) {
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
}

function sizeCanvas(canvas) {
  if (!canvas) return { ctx: null, w: 0, h: 0, dpr: 1 }
  const parent = canvas.parentElement
  const cssW = Math.max(280, parent?.clientWidth || 320)
  const cssH = 220
  const dpr = window.devicePixelRatio || 1
  canvas.width = Math.round(cssW * dpr)
  canvas.height = Math.round(cssH * dpr)
  canvas.style.width = `${cssW}px`
  canvas.style.height = `${cssH}px`
  const ctx = canvas.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  return { ctx, w: cssW, h: cssH, dpr }
}

function drawAxes(ctx, pad, w, h, { xLabel, yLabel }) {
  ctx.strokeStyle = '#888'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(pad.l, pad.t)
  ctx.lineTo(pad.l, h - pad.b)
  ctx.lineTo(w - pad.r, h - pad.b)
  ctx.stroke()
  ctx.fillStyle = '#444'
  ctx.font = '11px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(xLabel, (pad.l + w - pad.r) / 2, h - 6)
  ctx.save()
  ctx.translate(12, (pad.t + h - pad.b) / 2)
  ctx.rotate(-Math.PI / 2)
  ctx.fillText(yLabel, 0, 0)
  ctx.restore()
}

function drawHist() {
  const canvas = histCanvas.value
  const dist = report.value?.charts?.score_distribution
  if (!canvas || !dist?.bin_centers?.length) {
    clearCanvas(canvas)
    return
  }
  const { ctx, w, h } = sizeCanvas(canvas)
  if (!ctx) return
  const pad = { l: 40, r: 12, t: 16, b: 28 }
  const centers = dist.bin_centers
  const g = dist.genuine
  const imp = dist.impostor
  const maxY = Math.max(1, ...g, ...imp)
  const x0 = centers[0]
  const x1 = centers[centers.length - 1]
  const span = x1 - x0 || 1
  const barW = Math.max(1, ((w - pad.l - pad.r) / centers.length) * 0.9)

  drawAxes(ctx, pad, w, h, { xLabel: 'threshold', yLabel: 'count' })

  const xOf = (x) => pad.l + ((x - x0) / span) * (w - pad.l - pad.r)
  const yOf = (y) => h - pad.b - (y / maxY) * (h - pad.t - pad.b)

  for (let i = 0; i < centers.length; i++) {
    const x = xOf(centers[i]) - barW / 2
    ctx.fillStyle = 'rgba(220, 60, 60, 0.55)'
    const ih = h - pad.b - yOf(imp[i] || 0)
    ctx.fillRect(x, yOf(imp[i] || 0), barW, ih)
    ctx.fillStyle = 'rgba(40, 160, 70, 0.55)'
    const gh = h - pad.b - yOf(g[i] || 0)
    ctx.fillRect(x, yOf(g[i] || 0), barW, gh)
  }

  ctx.fillStyle = '#c0392b'
  ctx.fillRect(w - 110, 8, 12, 8)
  ctx.fillStyle = '#333'
  ctx.font = '10px sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText('Impostors', w - 94, 16)
  ctx.fillStyle = '#27ae60'
  ctx.fillRect(w - 110, 22, 12, 8)
  ctx.fillStyle = '#333'
  ctx.fillText('Genuines', w - 94, 30)
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
  const pad = { l: 44, r: 12, t: 16, b: 28 }
  drawAxes(ctx, pad, w, h, { xLabel: 'threshold', yLabel: '%' })

  const xs = series.map((p) => p.threshold)
  const x0 = Math.min(...xs)
  const x1 = Math.max(...xs)
  const span = x1 - x0 || 1
  const xOf = (x) => pad.l + ((x - x0) / span) * (w - pad.l - pad.r)
  const yOf = (pct) => h - pad.b - (Math.min(100, Math.max(0, pct)) / 100) * (h - pad.t - pad.b)

  ctx.strokeStyle = '#c0392b'
  ctx.lineWidth = 1.5
  ctx.beginPath()
  series.forEach((p, i) => {
    const x = xOf(p.threshold)
    const y = yOf(p.fmr_pct)
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.stroke()

  ctx.strokeStyle = '#27ae60'
  ctx.beginPath()
  series.forEach((p, i) => {
    const x = xOf(p.threshold)
    const y = yOf(p.fnmr_pct)
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.stroke()

  ctx.font = '10px sans-serif'
  ctx.fillStyle = '#c0392b'
  ctx.fillText('FMR', w - 50, 14)
  ctx.fillStyle = '#27ae60'
  ctx.fillText('FNMR', w - 50, 28)
}

function drawDet() {
  const canvas = detCanvas.value
  const series = report.value?.charts?.det
  if (!canvas || !series?.length) {
    clearCanvas(canvas)
    return
  }
  const { ctx, w, h } = sizeCanvas(canvas)
  if (!ctx) return
  const pad = { l: 48, r: 12, t: 16, b: 28 }
  drawAxes(ctx, pad, w, h, { xLabel: 'FMR (log)', yLabel: 'FNMR (log)' })

  const eps = 1e-6
  const fmrs = series.map((p) => Math.max(eps, p.fmr))
  const fnmrs = series.map((p) => Math.max(eps, p.fnmr))
  const logMinX = Math.log10(Math.min(...fmrs))
  const logMaxX = Math.log10(Math.max(...fmrs))
  const logMinY = Math.log10(Math.min(...fnmrs))
  const logMaxY = Math.log10(Math.max(...fnmrs))
  const spanX = logMaxX - logMinX || 1
  const spanY = logMaxY - logMinY || 1
  const xOf = (fmr) => pad.l + ((Math.log10(Math.max(eps, fmr)) - logMinX) / spanX) * (w - pad.l - pad.r)
  const yOf = (fnmr) => h - pad.b - ((Math.log10(Math.max(eps, fnmr)) - logMinY) / spanY) * (h - pad.t - pad.b)

  // EER diagonal (FMR == FNMR) where in range
  ctx.strokeStyle = '#999'
  ctx.setLineDash([4, 3])
  ctx.beginPath()
  const diagPts = []
  for (let i = 0; i <= 40; i++) {
    const t = i / 40
    const v = 10 ** (logMinX + t * spanX)
    if (v >= 10 ** logMinY && v <= 10 ** logMaxY) diagPts.push([xOf(v), yOf(v)])
  }
  diagPts.forEach(([x, y], i) => {
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.stroke()
  ctx.setLineDash([])

  // FMR reference lines
  const refs = [
    { fmr: 0.01, label: 'FMR100' },
    { fmr: 0.001, label: 'FMR1000' },
    { fmr: 0.0001, label: 'FMR10000' },
  ]
  ctx.strokeStyle = '#bbb'
  ctx.font = '9px sans-serif'
  ctx.fillStyle = '#666'
  refs.forEach(({ fmr, label }) => {
    if (fmr < 10 ** logMinX || fmr > 10 ** logMaxX) return
    const x = xOf(fmr)
    ctx.beginPath()
    ctx.moveTo(x, pad.t)
    ctx.lineTo(x, h - pad.b)
    ctx.stroke()
    ctx.fillText(label, x + 2, pad.t + 10)
  })

  ctx.strokeStyle = '#2471a3'
  ctx.lineWidth = 1.8
  ctx.beginPath()
  series.forEach((p, i) => {
    const x = xOf(p.fmr)
    const y = yOf(p.fnmr)
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.stroke()
}

function drawCharts() {
  drawHist()
  drawFmrFnmr()
  drawDet()
}

function onResize() {
  if (report.value) drawCharts()
}

watch(connectionKey, async () => {
  filters.dataset_code = String(route.query.dataset_code || '')
  await loadMeta()
  syncQuery()
})

watch(
  () => filters.dataset_code,
  async () => {
    await loadMeta()
  },
)

onMounted(async () => {
  filters.dataset_code = String(route.query.dataset_code || '')
  filters.score_column = String(route.query.score_column || 'score')
  await loadConnections()
  await loadMeta()
  if (filters.dataset_code && filters.score_column) {
    await loadReport()
  }
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
          <div class="chart-title">FMR(t) and FNMR(t)</div>
          <canvas ref="fmrCanvas" />
        </div>
        <div class="chart-box">
          <div class="chart-title">DET</div>
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
  gap: 12px;
  border: 1px solid #d4c4a0;
  border-top: none;
  padding: 12px;
  background: #fafafa;
}
.chart-box {
  min-width: 0;
}
.chart-title {
  text-align: center;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
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
