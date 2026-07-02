<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Clock } from '@element-plus/icons-vue'

const route = useRoute()
const description = computed(() => route.meta.description || '')
</script>

<template>
  <div class="page-card placeholder">
    <div class="placeholder-body">
      <div class="placeholder-icon">
        <el-icon :size="48" color="#909399"><Clock /></el-icon>
      </div>
      <h2 class="placeholder-title">{{ route.meta.title }}</h2>
      <p v-if="description" class="placeholder-desc">{{ description }}</p>
      <el-alert
        title="功能开发中"
        type="info"
        show-icon
        :closable="false"
        class="placeholder-alert"
      />
    </div>
  </div>
</template>

<style scoped>
.placeholder {
  min-height: calc(100vh - var(--header-height) - 80px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-body {
  text-align: center;
  max-width: 480px;
  padding: 24px;
}

.placeholder-icon {
  margin-bottom: 16px;
}

.placeholder-title {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}

.placeholder-desc {
  margin: 0 0 20px;
  color: #606266;
  line-height: 1.6;
}

.placeholder-alert {
  text-align: left;
}
</style>
