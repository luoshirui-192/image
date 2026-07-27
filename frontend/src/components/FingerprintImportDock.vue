<script setup>
/**
 * Fingerprint ZIP import jobs panel — used on 任务台.
 * Refresh is owned by the parent 任务台 page / layout restore; this panel only polls via store.
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useFingerprintImportStore } from '@/stores/fingerprintImport'
import FingerprintImportDialog from '@/components/FingerprintImportDialog.vue'

const store = useFingerprintImportStore()
const router = useRouter()
const importDialogVisible = ref(false)

onMounted(() => {
  void store.syncFromServer()
})

function statusLabel(status) {
  const map = {
    pending: '排队中',
    running: '导入中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[status] || status
}

function statusType(status) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'info'
  return 'warning'
}

function onImportStarted(job) {
  store.trackJob(job)
}

function openFingerprintBrowse() {
  void router.push({ path: '/fingerprint-pairs' })
}
</script>

<template>
  <div class="import-panel">
    <div class="import-panel-head">
      <h3>指纹 ZIP 导入</h3>
      <div class="import-panel-actions">
        <el-button type="primary" size="small" @click="importDialogVisible = true">导入 zip</el-button>
        <el-button link type="primary" size="small" @click="openFingerprintBrowse">打开指纹浏览</el-button>
        <el-button link type="primary" size="small" :loading="store.loadingList" @click="store.syncFromServer()">
          刷新
        </el-button>
        <el-button
          v-if="store.visibleJobs.some((j) => !['pending', 'running'].includes(j.status))"
          link
          type="primary"
          size="small"
          @click="store.clearFinished()"
        >
          清除已完成
        </el-button>
      </div>
    </div>
    <p class="field-hint">
      batmatch zip 导入与路径写回任务。可在此发起，也可在「指纹对比」页导入；进度统一在此查看。
    </p>

    <el-empty v-if="!store.hasVisible" description="暂无指纹导入任务" :image-size="64" />

    <div v-for="job in store.visibleJobs" :key="job.id" class="import-item">
      <div class="import-item-top">
        <span class="import-title">
          #{{ job.id }}
          {{ job.zip_name || '导入任务' }}
        </span>
        <el-tag size="small" :type="statusType(job.status)">{{ statusLabel(job.status) }}</el-tag>
      </div>
      <el-progress
        v-if="['pending', 'running'].includes(job.status)"
        :percentage="Number(job.percent || 0)"
        :indeterminate="!(job.percent > 0)"
        :stroke-width="10"
        :duration="3"
      />
      <div class="import-meta">
        <template v-if="['pending', 'running'].includes(job.status)">
          {{ job.message || '导入中…' }}
          · {{ job.processed || 0 }}
          <template v-if="job.total_estimate"> / {{ job.total_estimate }}</template>
          · 成功 {{ job.succeeded || 0 }} / 跳过 {{ job.skipped || 0 }} / 失败 {{ job.failed || 0 }}
        </template>
        <template v-else>
          {{ job.message || statusLabel(job.status) }}
          · 成功 {{ job.succeeded || 0 }} / 跳过 {{ job.skipped || 0 }} / 失败 {{ job.failed || 0 }}
        </template>
        <template v-if="job.path_writeback_enabled">
          · 写回 插入 {{ job.writeback_inserted || job.writeback_updated || 0 }}
          / 失败 {{ job.writeback_failed || 0 }}
        </template>
      </div>
      <div
        v-if="job.path_writeback_enabled && (job.writeback_errors || []).length"
        class="import-errors"
      >
        <div v-for="(err, idx) in job.writeback_errors.slice(0, 5)" :key="idx">{{ err }}</div>
      </div>
      <div class="import-actions">
        <el-button
          v-if="['pending', 'running'].includes(job.status)"
          size="small"
          @click="store.cancelJob(job.id)"
        >
          取消
        </el-button>
        <el-button
          v-if="job.status === 'completed'"
          size="small"
          type="primary"
          @click="openFingerprintBrowse"
        >
          打开指纹浏览
        </el-button>
        <el-button
          v-if="!['pending', 'running'].includes(job.status)"
          size="small"
          link
          @click="store.dismissJob(job.id)"
        >
          关闭
        </el-button>
      </div>
    </div>

    <FingerprintImportDialog v-model="importDialogVisible" @started="onImportStarted" />
  </div>
</template>

<style scoped>
.import-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.import-panel-head h3 {
  margin: 0;
  font-size: 16px;
}
.import-panel-actions {
  display: flex;
  gap: 4px;
  align-items: center;
  flex-wrap: wrap;
}
.field-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.import-item {
  margin-top: 10px;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}
.import-item-top {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}
.import-title {
  font-size: 13px;
  font-weight: 600;
  word-break: break-all;
}
.import-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}
.import-errors {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-color-danger);
  max-height: 80px;
  overflow: auto;
}
.import-actions {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
</style>
