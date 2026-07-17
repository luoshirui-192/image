<script setup>
/**
 * Legacy compare route — redirect into the unified pairs page (left tree + right compare).
 */
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

onMounted(() => {
  const id = route.params.id
  router.replace({
    name: 'fingerprint-pairs',
    query: id ? { id: String(id) } : {},
  })
})
</script>

<template>
  <div class="redirect">正在打开对比视图…</div>
</template>

<style scoped>
.redirect {
  padding: 24px;
  color: var(--el-text-color-secondary);
}
</style>
