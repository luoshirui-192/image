<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { fetchImageBlob } from '@/api/images'

const props = defineProps({
  items: {
    type: Array,
    default: () => [],
  },
  currentIndex: {
    type: Number,
    default: -1,
  },
})

const emit = defineEmits(['update:currentIndex', 'close'])

const thumbUrls = ref({})
const mainSrc = ref('')
const loadingMain = ref(false)

let objectUrls = []
let abortController = null

const activeItem = computed(() => {
  if (props.currentIndex < 0 || !props.items.length) return null
  return props.items[props.currentIndex] || null
})

function revokeUrls() {
  objectUrls.forEach((url) => URL.revokeObjectURL(url))
  objectUrls = []
  thumbUrls.value = {}
  mainSrc.value = ''
}

function abortPending() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
}

async function refreshThumbs() {
  abortPending()
  revokeUrls()
  if (!props.items.length) return
  const next = {}
  for (const item of props.items) {
    try {
      const blob = await fetchImageBlob(item.path, { id: item.id, thumb: true })
      const url = URL.createObjectURL(blob)
      objectUrls.push(url)
      next[item.id] = url
    } catch {
      next[item.id] = ''
    }
  }
  thumbUrls.value = next
}

async function refreshMain() {
  abortPending()
  mainSrc.value = ''
  const item = activeItem.value
  if (!item) return
  loadingMain.value = true
  try {
    const blob = await fetchImageBlob(item.path, { id: item.id, thumb: false, signal: undefined })
    const url = URL.createObjectURL(blob)
    objectUrls.push(url)
    mainSrc.value = url
  } catch {
    mainSrc.value = ''
  } finally {
    loadingMain.value = false
  }
}

function selectIndex(index) {
  emit('update:currentIndex', index)
}

watch(
  () => props.items,
  () => {
    refreshThumbs()
    refreshMain()
  },
  { deep: true, immediate: true },
)

watch(
  () => props.currentIndex,
  () => {
    refreshMain()
  },
)

onUnmounted(() => {
  abortPending()
  revokeUrls()
})
</script>

<template>
  <div v-if="items.length" class="multi-blob-preview">
    <div class="preview-head">
      <span>多 BLOB 预览</span>
      <span class="preview-count">{{ items.length }} 列</span>
      <el-button link :icon="Close" @click="emit('close')" />
    </div>

    <div class="thumb-strip">
      <button
        v-for="(item, index) in items"
        :key="`${item.id}:${item.column}`"
        type="button"
        :class="['thumb-item', { active: index === currentIndex }]"
        @click="selectIndex(index)"
      >
        <img v-if="thumbUrls[item.id]" :src="thumbUrls[item.id]" :alt="item.column" />
        <div v-else class="thumb-placeholder">…</div>
        <span class="thumb-label">{{ item.column }}</span>
      </button>
    </div>

    <div v-if="activeItem" v-loading="loadingMain" class="main-preview">
      <img v-if="mainSrc" :src="mainSrc" :alt="activeItem.column" />
      <div v-else class="main-empty">无法加载预览</div>
      <div class="main-caption">{{ activeItem.title || activeItem.path }}</div>
    </div>
  </div>
  <div v-else class="multi-blob-empty">
    点击表格行查看已迁移的 BLOB 预览
  </div>
</template>

<style scoped>
.multi-blob-preview {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  height: 100%;
}

.preview-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
}

.preview-count {
  margin-right: auto;
  font-weight: normal;
  color: var(--el-text-color-secondary);
}

.thumb-strip {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.thumb-item {
  flex: 0 0 88px;
  border: 2px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  padding: 4px;
  cursor: pointer;
}

.thumb-item.active {
  border-color: var(--el-color-primary);
}

.thumb-item img,
.thumb-placeholder {
  width: 100%;
  height: 64px;
  object-fit: cover;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.thumb-label {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.main-preview {
  flex: 1;
  min-height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px;
  overflow: hidden;
}

.main-preview img {
  max-width: 100%;
  max-height: calc(100% - 24px);
  object-fit: contain;
}

.main-caption {
  margin-top: 6px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  text-align: center;
  word-break: break-all;
}

.main-empty,
.multi-blob-empty {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  text-align: center;
  padding: 16px 8px;
}
</style>
