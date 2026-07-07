<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
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
const thumbStripRef = ref(null)
const loading = ref(false)
const src = ref('')
const thumbUrls = ref({})

let objectUrl = ''
let thumbObjectUrls = []
let abortController = null
let wheelLocked = false
let thumbLoadGeneration = 0

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

function thumbItemKey(item, index) {
  return `${index}:${item.id ?? ''}:${item.column ?? ''}:${item.path ?? ''}`
}

function thumbLabel(item, index) {
  return item.column || item.title || `图片 ${index + 1}`
}

function revokeUrl() {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
    objectUrl = ''
  }
  src.value = ''
}

function revokeThumbUrls() {
  thumbObjectUrls.forEach((url) => URL.revokeObjectURL(url))
  thumbObjectUrls = []
  thumbUrls.value = {}
}

function abortPending() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
}

async function refreshThumbs() {
  const gen = ++thumbLoadGeneration
  revokeThumbUrls()
  if (!props.items.length) return

  const next = {}
  for (let index = 0; index < props.items.length; index += 1) {
    const item = props.items[index]
    if (!item?.path && item?.id == null) continue
    try {
      const blob = await fetchImageBlob(item.path, { id: item.id, thumb: true })
      if (gen !== thumbLoadGeneration) return
      const url = URL.createObjectURL(blob)
      thumbObjectUrls.push(url)
      next[index] = url
    } catch {
      if (gen !== thumbLoadGeneration) return
      next[index] = ''
    }
  }
  if (gen !== thumbLoadGeneration) return
  thumbUrls.value = next
}

function scrollActiveThumbIntoView() {
  nextTick(() => {
    const strip = thumbStripRef.value
    if (!strip) return
    const activeEl = strip.querySelector('.thumb-item.active')
    activeEl?.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'smooth' })
  })
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
  () => props.items,
  () => {
    refreshThumbs()
  },
  { deep: true, immediate: true },
)

watch(
  () => props.currentIndex,
  () => {
    scrollActiveThumbIntoView()
  },
)

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
  revokeThumbUrls()
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

    <div
      v-if="total > 1"
      ref="thumbStripRef"
      class="thumb-strip"
      aria-label="横向浏览缩略图"
    >
      <button
        v-for="(item, index) in items"
        :key="thumbItemKey(item, index)"
        type="button"
        :class="['thumb-item', { active: index === currentIndex }]"
        :title="item.title || item.path || `图片 ${index + 1}`"
        @click="setIndex(index)"
      >
        <img
          v-if="thumbUrls[index]"
          :src="thumbUrls[index]"
          :alt="thumbLabel(item, index)"
        />
        <div v-else class="thumb-placeholder">…</div>
        <span class="thumb-label">{{ thumbLabel(item, index) }}</span>
      </button>
    </div>

    <p v-if="active && total > 1" class="panel-hint">
      底部横向滑动浏览，或用 ↑↓ / 滚轮切换
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
  min-height: 180px;
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
  min-height: 140px;
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

.thumb-strip {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 0 12px 8px;
  flex-shrink: 0;
  scrollbar-width: thin;
}

.thumb-strip::-webkit-scrollbar {
  height: 8px;
}

.thumb-strip::-webkit-scrollbar-thumb {
  border-radius: 4px;
  background: var(--el-border-color);
}

.thumb-item {
  flex: 0 0 72px;
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
  height: 56px;
  object-fit: cover;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  display: block;
}

.thumb-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-placeholder);
  font-size: 14px;
}

.thumb-label {
  display: block;
  margin-top: 4px;
  font-size: 10px;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-secondary);
}

.panel-hint {
  margin: 0;
  padding: 0 12px 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  text-align: center;
}
</style>
