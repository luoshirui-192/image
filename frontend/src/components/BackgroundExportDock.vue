<script setup>
/**
 * Inline panel for path/simulated export jobs — used on 迁移任务台 (not a floating overlay).
 */
import { useRouter } from 'vue-router'
import { useBackgroundExportStore } from '@/stores/backgroundExport'

const store = useBackgroundExportStore()
const router = useRouter()

function statusLabel(status) {
  const map = {
    pending: '排队中',
    running: '导出中',
    paused: '已暂停',
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
  if (status === 'paused') return 'warning'
  return 'warning'
}

async function openResult(job) {
  const viewId = job?.result?.target_view_id
  if (viewId) {
    await router.push({ path: '/blob-browse', query: { viewId: String(viewId) } })
  } else {
    await router.push({ path: '/blob-browse' })
  }
}
</script>

<template>
  <div class="export-panel">
    <div class="export-panel-head">
      <h3>路径导出任务</h3>
      <el-button
        v-if="store.visibleJobs.some((j) => !['pending', 'running', 'paused'].includes(j.status))"
        link
        type="primary"
        size="small"
        @click="store.clearFinished()"
      >
        清除已完成
      </el-button>
    </div>
    <p class="field-hint">
      全局串行排队：仅在完成、失败、取消或删除后自动开始下一个；暂停会占住队列位，不会开下一个。
      支持断点续传；容器重启后会自动重新排队续跑。
    </p>

    <el-empty
      v-if="!store.hasVisible"
      description="暂无路径导出任务"
      :image-size="64"
    />

    <div v-for="job in store.visibleJobs" :key="job.id" class="export-item">
      <div class="export-item-top">
        <span class="export-title">
          #{{ job.id }}
          {{ job.target_database || '' }}.{{ job.target_table || '表' }}
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
      <div class="export-meta">
        <template v-if="['pending', 'running'].includes(job.status)">
          {{ job.message || '导出中…' }}
          · {{ job.rows_written || 0 }}
          <template v-if="job.total_estimate"> / {{ job.total_estimate }}</template>
          行
        </template>
        <template v-else>
          {{ job.message || statusLabel(job.status) }}
        </template>
      </div>
      <div class="export-actions">
        <el-button
          v-if="['pending', 'running'].includes(job.status)"
          size="small"
          type="warning"
          plain
          @click="store.pauseJob(job.id)"
        >
          暂停
        </el-button>
        <el-button
          v-if="job.status === 'paused'"
          size="small"
          type="primary"
          @click="store.resumeJob(job.id)"
        >
          继续
        </el-button>
        <el-button
          v-if="['pending', 'running', 'paused'].includes(job.status)"
          size="small"
          @click="store.cancelJob(job.id)"
        >
          取消
        </el-button>
        <el-button
          v-if="job.status === 'completed' && job.result?.target_view_id"
          size="small"
          type="primary"
          @click="openResult(job)"
        >
          打开目标
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
  </div>
</template>

<style scoped>
.export-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.export-panel-head h3 {
  margin: 0;
  font-size: 16px;
}
.field-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.export-item {
  margin-top: 10px;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}
.export-item-top {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}
.export-title {
  font-size: 13px;
  font-weight: 600;
  word-break: break-all;
}
.export-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}
.export-actions {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
</style>
