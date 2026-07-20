<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useBackgroundExportStore } from '@/stores/backgroundExport'

const store = useBackgroundExportStore()
const router = useRouter()

onMounted(() => {
  void store.restoreFromSession()
})

onUnmounted(() => {
  // Keep global polling alive across layout remounts only if still active —
  // layout rarely unmounts; stop only when no active jobs.
  if (!store.activeJobs.length) store.stopPolling()
})

function statusLabel(status) {
  const map = {
    pending: '排队中',
    running: '导出中',
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
  <div v-if="store.hasVisible" class="bg-export-dock">
    <div class="dock-head">
      <strong>后台导出</strong>
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
    <div v-for="job in store.visibleJobs" :key="job.id" class="dock-item">
      <div class="dock-item-top">
        <span class="dock-title">
          #{{ job.id }}
          {{ job.target_database || '' }}.{{ job.target_table || '表' }}
        </span>
        <el-tag size="small" :type="statusType(job.status)">{{ statusLabel(job.status) }}</el-tag>
      </div>
      <el-progress
        v-if="['pending', 'running'].includes(job.status)"
        :percentage="Number(job.percent || 0)"
        :indeterminate="!(job.percent > 0)"
        :stroke-width="8"
        :duration="3"
      />
      <div class="dock-meta">
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
      <div class="dock-actions">
        <el-button
          v-if="['pending', 'running'].includes(job.status)"
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
.bg-export-dock {
  position: fixed;
  right: 20px;
  bottom: 48px;
  z-index: 3000;
  width: min(360px, calc(100vw - 32px));
  max-height: min(50vh, 420px);
  overflow: auto;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 10px;
  box-shadow: 0 8px 28px rgb(0 0 0 / 14%);
  padding: 10px 12px;
}
.dock-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
}
.dock-item {
  padding: 8px 0;
  border-top: 1px solid var(--el-border-color-extra-light);
}
.dock-item:first-of-type {
  border-top: none;
}
.dock-item-top {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}
.dock-title {
  font-size: 12px;
  font-weight: 600;
  word-break: break-all;
}
.dock-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}
.dock-actions {
  margin-top: 6px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
</style>
