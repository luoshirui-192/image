<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, Close } from '@element-plus/icons-vue'
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
  thumb: { type: Boolean, default: false },
})

const emit = defineEmits(['update:currentIndex'])

const panelRef = ref(null)
const loading = ref(false)
const src = ref('')

let objectUrl = ''
let abortController = null
let wheelLocked = false

const active = computed(() => props.currentIndex >= 0 && props.items.length > 0)
const total = computed(() => props.items.length)
const currentItem = computed(() => {
  if (!active.value) return null
  return props.items[props.currentIndex] || null
})
const canPrev = computed(() => props.currentIndex > 0)
const canNext = computed(() => props.currentIndex >= 0 && props.currentIndex < props.items.length - 1)

const panelTitle = computed(() => {
  const item = currentItem.value
  if (!item) return '图片预览'
  const name = item.title || item.path || '预览'
  if (total.value > 1) {
    return `${name}（${props.currentIndex + 1} / ${total.value}）`
  }
  return name
})

function revokeUrl() {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
    objectUrl = ''
  }
  src.value = ''
}

function abortPending() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
}

async function loadCurrent() {
  const item = currentItem.value
  if (!item?.path && item?.id == null) {
    revokeUrl()
    return
  }

  abortPending()
  revokeUrl()
  loading.value = true
  abortController = new AbortController()
  const { signal } = abortController

  try {
    const blob = await fetchImageBlob(item.path, {
      id: item.id,
      thumb: props.thumb,
      signal,
    })
    if (signal.aborted) return
    objectUrl = URL.createObjectURL(blob)
    src.value = objectUrl
  } catch {
    if (signal.aborted) return
    src.value = ''
  } finally {
    if (!signal.aborted) {
      loading.value = false
    }
  }
}

function setIndex(index) {
  if (index < 0 || index >= props.items.length) {
    emit('update:currentIndex', -1)
    return
  }
  emit('update:currentIndex', index)
}

function goPrev() {
  if (!canPrev.value || loading.value) return
  setIndex(props.currentIndex - 1)
}

function goNext() {
  if (!canNext.value || loading.value) return
  setIndex(props.currentIndex + 1)
}

function clearPreview() {
  emit('update:currentIndex', -1)
}

function onKeydown(event) {
  if (!active.value) return
  if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    event.preventDefault()
    goPrev()
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    event.preventDefault()
    goNext()
  } else if (event.key === 'Escape') {
    clearPreview()
  }
}

function onWheel(event) {
  if (!active.value || wheelLocked || total.value <= 1) return
  event.preventDefault()
  wheelLocked = true
  window.setTimeout(() => {
    wheelLocked = false
  }, 200)
  if (event.deltaY > 0) {
    goNext()
  } else if (event.deltaY < 0) {
    goPrev()
  }
}

watch(
  () => [props.currentIndex, props.items],
  () => {
    if (active.value) {
      loadCurrent()
    } else {
      abortPending()
      revokeUrl()
    }
  },
  { deep: true },
)

onUnmounted(() => {
  abortPending()
  revokeUrl()
})
</script>

<template>
  <aside class="gallery-panel">
    <div class="panel-head">
      <span class="panel-title" :title="panelTitle">{{ panelTitle }}</span>
      <el-button
        v-if="active"
        link
        type="info"
        :icon="Close"
        aria-label="关闭预览"
        @click="clearPreview"
      />
    </div>

    <div
      ref="panelRef"
      class="panel-body"
      tabindex="0"
      @keydown="onKeydown"
      @wheel.prevent="onWheel"
    >
      <template v-if="active">
        <el-button
          v-if="total > 1"
          class="nav-btn prev"
          circle
          size="small"
          :icon="ArrowLeft"
          :disabled="!canPrev || loading"
          @click="goPrev"
        />
        <div v-loading="loading" class="image-wrap">
          <img v-if="src" :src="src" alt="预览" class="gallery-image" />
          <el-empty v-else-if="!loading" description="无法加载图片" :image-size="64" />
        </div>
        <el-button
          v-if="total > 1"
          class="nav-btn next"
          circle
          size="small"
          :icon="ArrowRight"
          :disabled="!canNext || loading"
          @click="goNext"
        />
      </template>
      <el-empty v-else description="点击缩略图或数据行预览" :image-size="72" />
    </div>

    <p v-if="active && total > 1" class="panel-hint">
      聚焦预览框后，可用 ↑↓ 或滚轮切换
    </p>
  </aside>
</template>

<style scoped>
.gallery-panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color);
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  min-height: 280px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-shrink: 0;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-body {
  flex: 1;
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  outline: none;
}

.panel-body:focus {
  box-shadow: inset 0 0 0 1px var(--el-color-primary-light-5);
}

.image-wrap {
  flex: 1;
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.gallery-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.nav-btn {
  flex-shrink: 0;
}

.panel-hint {
  margin: 0;
  padding: 0 12px 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  text-align: center;
}
</style>
