<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteFingerprintPairApi,
  fetchFingerprintMetaApi,
  fetchFingerprintPairsApi,
  importFingerprintZipApi,
} from '@/api/fingerprints'

const router = useRouter()
const loading = ref(false)
const importing = ref(false)
const rows = ref([])
const total = ref(0)
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
  page: 1,
  page_size: 20,
})

const layerTypeLabel = computed(() => {
  const map = {}
  for (const item of meta.layer_types) {
    map[item.layer_key] = item.label || item.layer_key
  }
  return map
})

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
      page: filters.page,
      page_size: filters.page_size,
    }
    for (const key of ['keyword', 'finger_position', 'batch_name', 'layer_type', 'algo_version']) {
      if (filters[key]) params[key] = filters[key]
    }
    if (filters.score_min != null && filters.score_min !== '') params.score_min = filters.score_min
    if (filters.score_max != null && filters.score_max !== '') params.score_max = filters.score_max
    const res = await fetchFingerprintPairsApi(params)
    rows.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (err) {
    ElMessage.error(err.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  filters.page = 1
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
  filters.page = 1
  loadPairs()
}

function openCompare(row) {
  router.push({ name: 'fingerprint-compare', params: { id: row.id } })
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`确认删除配对 ${row.batch_name}？`, '删除确认', { type: 'warning' })
    await deleteFingerprintPairApi(row.id)
    ElMessage.success('已删除')
    loadPairs()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.message || '删除失败')
  }
}

async function onZipChange(uploadFile) {
  const file = uploadFile.raw
  if (!file) return
  importing.value = true
  try {
    const res = await importFingerprintZipApi(file, { algo_version: '1.0', skip_existing: true })
    ElMessage.success(`导入完成：新增 ${res.data.imported}，跳过 ${res.data.skipped}`)
    await loadMeta()
    await loadPairs()
  } catch (err) {
    ElMessage.error(err.message || '导入失败')
  } finally {
    importing.value = false
  }
}

onMounted(async () => {
  await loadMeta()
  await loadPairs()
})
</script>

<template>
  <div class="fp-page">
    <div class="fp-toolbar">
      <div class="fp-title">
        <h2>指纹成对对比</h2>
        <p>筛选 batmatch 风格配对，进入双栏特征叠加对比</p>
      </div>
      <el-upload
        :show-file-list="false"
        accept=".zip"
        :disabled="importing"
        :auto-upload="false"
        :on-change="onZipChange"
      >
        <el-button type="primary" :loading="importing">导入 zip</el-button>
      </el-upload>
    </div>

    <el-card shadow="never" class="fp-filters">
      <el-form :inline="true" @submit.prevent="onSearch">
        <el-form-item label="关键词">
          <el-input v-model="filters.keyword" clearable placeholder="人名/文件名/批次" style="width: 180px" />
        </el-form-item>
        <el-form-item label="指位">
          <el-select v-model="filters.finger_position" clearable placeholder="全部" style="width: 160px">
            <el-option v-for="p in meta.finger_positions" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="批次">
          <el-input v-model="filters.batch_name" clearable style="width: 140px" />
        </el-form-item>
        <el-form-item label="特征层">
          <el-select v-model="filters.layer_type" clearable placeholder="全部" style="width: 140px">
            <el-option
              v-for="t in meta.layer_types"
              :key="t.layer_key"
              :label="t.label"
              :value="t.layer_key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="版本">
          <el-select v-model="filters.algo_version" clearable placeholder="全部" style="width: 120px">
            <el-option v-for="v in meta.algo_versions" :key="v" :label="v" :value="v" />
          </el-select>
        </el-form-item>
        <el-form-item label="分数">
          <el-input-number v-model="filters.score_min" :controls="false" placeholder="min" style="width: 90px" />
          <span class="sep">~</span>
          <el-input-number v-model="filters.score_max" :controls="false" placeholder="max" style="width: 90px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="onSearch">查询</el-button>
          <el-button @click="onReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-table v-loading="loading" :data="rows" stripe border style="width: 100%">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="batch_name" label="批次" min-width="140" />
      <el-table-column prop="finger_position" label="指位" width="130" />
      <el-table-column prop="match_score" label="分数" width="100" />
      <el-table-column label="左图" min-width="180">
        <template #default="{ row }">{{ row.left_image_name }}</template>
      </el-table-column>
      <el-table-column label="右图" min-width="180">
        <template #default="{ row }">{{ row.right_image_name }}</template>
      </el-table-column>
      <el-table-column label="特征层" min-width="140">
        <template #default="{ row }">
          <el-tag
            v-for="t in row.layer_types"
            :key="t"
            size="small"
            class="tag"
          >{{ layerTypeLabel[t] || t }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="版本" width="120">
        <template #default="{ row }">{{ (row.algo_versions || []).join(', ') }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openCompare(row)">对比</el-button>
          <el-button link type="danger" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="filters.page"
        v-model:page-size="filters.page_size"
        layout="total, prev, pager, next, sizes"
        :total="total"
        :page-sizes="[10, 20, 50]"
        @current-change="loadPairs"
        @size-change="() => { filters.page = 1; loadPairs() }"
      />
    </div>
  </div>
</template>

<style scoped>
.fp-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.fp-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
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
.fp-filters :deep(.el-form-item) {
  margin-bottom: 8px;
}
.sep {
  margin: 0 6px;
  color: var(--el-text-color-secondary);
}
.tag {
  margin-right: 4px;
}
.pager {
  display: flex;
  justify-content: flex-end;
}
</style>
