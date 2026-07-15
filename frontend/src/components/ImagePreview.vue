<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Picture, ZoomIn } from '@element-plus/icons-vue'
import { fetchImageBlob } from '@/api/images'
import { callWithRetry } from '@/utils/callWithRetry'

const props = defineProps({
  imageId: { type: [Number, String], default: null },
  imagePath: { type: String, default: '' },
  size: { type: Number, default: 80 },
  fit: { type: String, default: 'cover' },
  thumb: { type: Boolean, default: true },
  /** Show zoom cursor and open a full-size lightbox on click. */
  clickable: { type: Boolean, default: false },
  lazy: { type: Boolean, default: true },
})

const emit = defineEmits(['click'])

const rootRef = ref(null)
const src = ref('')
const loading = ref(false)
const failed = ref(false)
const visible = ref(!props.lazy)

const lightboxVisible = ref(false)
const lightboxSrc = ref('')
const lightboxLoading = ref(false)
const lightboxFailed = ref(false)

let objectUrl = ''
let lightboxObjectUrl = ''
let abortController = null
let lightboxAbort = null
let observer = null
let fallbackTimer = null

function revokeObjectUrl() {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
    objectUrl = ''
  }
  src.value = ''
}

function revokeLightboxUrl() {
  if (lightboxObjectUrl) {
    URL.revokeObjectURL(lightboxObjectUrl)
    lightboxObjectUrl = ''
  }
  lightboxSrc.value = ''
}

function abortPending() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
}

function abortLightbox() {
  if (lightboxAbort) {
    lightboxAbort.abort()
    lightboxAbort = null
  }
}

function clearFallbackTimer() {
  if (fallbackTimer) {
    clearTimeout(fallbackTimer)
    fallbackTimer = null
  }
}

function resolveImageId() {
  if (props.imageId == null || props.imageId === '') return null
  const n = Number(props.imageId)
  return Number.isFinite(n) ? n : null
}

async function loadPreview() {
  if (!visible.value) return

  abortPending()
  revokeObjectUrl()
  failed.value = false

  if (!props.imageId && !props.imagePath) {
    failed.value = true
    return
  }

  loading.value = true
  abortController = new AbortController()
  const signal = abortController.signal

  try {
    const blob = await callWithRetry(
      () => fetchImageBlob(props.imagePath, {
        id: resolveImageId(),
        thumb: props.thumb,
        signal,
      }),
      { attempts: 3, delayMs: 300 },
    )
    if (signal.aborted) return
    objectUrl = URL.createObjectURL(blob)
    src.value = objectUrl
  } catch {
    if (signal.aborted) return
    failed.value = true
  } finally {
    if (!signal.aborted) {
      loading.value = false
    }
  }
}

async function loadLightbox() {
  abortLightbox()
  revokeLightboxUrl()
  lightboxFailed.value = false

  if (!props.imageId && !props.imagePath) {
    lightboxFailed.value = true
    return
  }

  lightboxLoading.value = true
  lightboxAbort = new AbortController()
  const signal = lightboxAbort.signal

  try {
    const blob = await callWithRetry(
      () => fetchImageBlob(props.imagePath, {
        id: resolveImageId(),
        thumb: false,
        signal,
      }),
      { attempts: 3, delayMs: 300 },
    )
    if (signal.aborted) return
    lightboxObjectUrl = URL.createObjectURL(blob)
    lightboxSrc.value = lightboxObjectUrl
  } catch {
    if (signal.aborted) return
    lightboxFailed.value = true
  } finally {
    if (!signal.aborted) {
      lightboxLoading.value = false
    }
  }
}

function openLightbox() {
  if (!props.clickable) return
  emit('click')
  lightboxVisible.value = true
  void loadLightbox()
}

function onLightboxClosed() {
  abortLightbox()
  revokeLightboxUrl()
  lightboxFailed.value = false
  lightboxLoading.value = false
}

function scheduleLazyFallback() {
  clearFallbackTimer()
  fallbackTimer = setTimeout(() => {
    if (src.value || loading.value || failed.value || !props.lazy) return
    visible.value = true
    observer?.disconnect()
    observer = null
    loadPreview()
  }, 500)
}

function setupObserver() {
  observer?.disconnect()
  observer = null

  if (!props.lazy || typeof IntersectionObserver === 'undefined') {
    visible.value = true
    return
  }

  if (!rootRef.value) return

  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        visible.value = true
        observer?.disconnect()
        observer = null
        clearFallbackTimer()
        loadPreview()
      }
    },
    { rootMargin: '160px' },
  )
  observer.observe(rootRef.value)
  scheduleLazyFallback()
}

watch(
  () => [props.imageId, props.imagePath, props.thumb],
  async () => {
    failed.value = false
    if (lightboxVisible.value) {
      void loadLightbox()
    }
    if (!props.lazy) {
      visible.value = true
      await loadPreview()
      return
    }
    visible.value = false
    revokeObjectUrl()
    await nextTick()
    setupObserver()
  },
)

watch(
  () => props.lazy,
  async (lazy) => {
    if (!lazy) {
      visible.value = true
      observer?.disconnect()
      observer = null
      clearFallbackTimer()
      await loadPreview()
    } else {
      visible.value = false
      await nextTick()
      setupObserver()
    }
  },
)

onMounted(async () => {
  await nextTick()
  if (props.lazy) {
    setupObserver()
  } else {
    visible.value = true
    await loadPreview()
  }
})

onUnmounted(() => {
  observer?.disconnect()
  clearFallbackTimer()
  abortPending()
  abortLightbox()
  revokeObjectUrl()
  revokeLightboxUrl()
})
</script>

<template>
  <div
    ref="rootRef"
    class="image-preview"
    :class="{ clickable }"
    :style="{ width: `${size}px`, height: `${size}px` }"
    :title="clickable ? '点击放大' : undefined"
    v-loading="loading"
    @click.stop="openLightbox"
  >
    <img v-if="src" :src="src" :alt="imagePath || 'preview'" :style="{ objectFit: fit }" />
    <div v-else-if="failed" class="placeholder failed">
      <el-icon><Picture /></el-icon>
    </div>
    <div v-else-if="lazy && !visible" class="placeholder lazy-hint">
      <el-icon><Picture /></el-icon>
    </div>
    <div v-else-if="!loading && !failed" class="placeholder">
      <el-icon><Picture /></el-icon>
    </div>
    <div v-if="clickable && src" class="zoom-badge" aria-hidden="true">
      <el-icon :size="12"><ZoomIn /></el-icon>
    </div>
  </div>

  <el-dialog
    v-model="lightboxVisible"
    class="image-lightbox-dialog"
    width="min(92vw, 1100px)"
    top="4vh"
    append-to-body
    destroy-on-close
    :show-close="true"
    @closed="onLightboxClosed"
  >
    <template #header>
      <div class="lightbox-header">
        <span>图片预览</span>
        <span v-if="imagePath" class="lightbox-path" :title="imagePath">{{ imagePath }}</span>
      </div>
    </template>
    <div v-loading="lightboxLoading" class="lightbox-body">
      <img
        v-if="lightboxSrc"
        :src="lightboxSrc"
        :alt="imagePath || 'preview'"
        class="lightbox-img"
      />
      <div v-else-if="lightboxFailed" class="lightbox-empty">无法加载原图</div>
      <div v-else class="lightbox-empty">加载中…</div>
    </div>
  </el-dialog>
</template>

<style scoped>
.image-preview {
  position: relative;
  border-radius: 6px;
  overflow: hidden;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  flex-shrink: 0;
}

.image-preview img {
  width: 100%;
  height: 100%;
  display: block;
}

.placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c0c4cc;
}

.placeholder.failed {
  background: #fef0f0;
  color: #f56c6c;
}

.placeholder.lazy-hint {
  background: #fafafa;
}

.image-preview.clickable {
  cursor: zoom-in;
}

.image-preview.clickable:hover {
  border-color: #409eff;
}

.zoom-badge {
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  background: rgb(0 0 0 / 55%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.lightbox-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding-right: 24px;
}

.lightbox-path {
  font-size: 12px;
  font-weight: normal;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lightbox-body {
  min-height: 40vh;
  max-height: 82vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #111;
  border-radius: 6px;
  overflow: auto;
}

.lightbox-img {
  max-width: 100%;
  max-height: 82vh;
  object-fit: contain;
  display: block;
}

.lightbox-empty {
  color: #c0c4cc;
  font-size: 14px;
  padding: 40px 16px;
}
</style>
