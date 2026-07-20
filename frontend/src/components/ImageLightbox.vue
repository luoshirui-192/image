<script setup>
import { onUnmounted, ref, watch } from 'vue'
import { fetchImageBlob } from '@/api/images'
import { callWithRetry } from '@/utils/callWithRetry'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  imageId: { type: [Number, String], default: null },
  imagePath: { type: String, default: '' },
  title: { type: String, default: '' },
  hint: { type: String, default: '↑↓ 换行 · Esc 关闭' },
})

const emit = defineEmits(['update:modelValue', 'prev', 'next'])

const src = ref('')
const loading = ref(false)
const failed = ref(false)

let objectUrl = ''
let abortController = null

function revoke() {
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

function resolveImageId() {
  if (props.imageId == null || props.imageId === '') return null
  const n = Number(props.imageId)
  return Number.isFinite(n) ? n : null
}

async function loadFull() {
  abortPending()
  revoke()
  failed.value = false
  if (!props.imageId && !props.imagePath) {
    // Intentionally empty (e.g. no_data row while browsing ↑↓) — not a load failure.
    loading.value = false
    return
  }
  loading.value = true
  abortController = new AbortController()
  const signal = abortController.signal
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
    objectUrl = URL.createObjectURL(blob)
    src.value = objectUrl
  } catch {
    if (signal.aborted) return
    failed.value = true
  } finally {
    if (!signal.aborted) loading.value = false
  }
}

function close() {
  emit('update:modelValue', false)
}

function onClosed() {
  abortPending()
  revoke()
  failed.value = false
  loading.value = false
}

function onKeydown(event) {
  if (!props.modelValue) return
  if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    event.preventDefault()
    event.stopPropagation()
    emit('prev')
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    event.preventDefault()
    event.stopPropagation()
    emit('next')
  } else if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

watch(
  () => [props.modelValue, props.imageId, props.imagePath],
  ([open]) => {
    if (open) {
      void loadFull()
      window.addEventListener('keydown', onKeydown, true)
    } else {
      window.removeEventListener('keydown', onKeydown, true)
      onClosed()
    }
  },
)

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown, true)
  abortPending()
  revoke()
})
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    class="image-lightbox-dialog"
    width="min(92vw, 1100px)"
    top="4vh"
    append-to-body
    destroy-on-close
    :show-close="true"
    @update:model-value="emit('update:modelValue', $event)"
    @closed="onClosed"
    @keydown="onKeydown"
  >
    <template #header>
      <div class="lightbox-header">
        <span>图片预览</span>
        <span v-if="title || imagePath" class="lightbox-path" :title="title || imagePath">
          {{ title || imagePath }}
        </span>
        <span class="lightbox-hint">{{ hint }}</span>
      </div>
    </template>
    <div
      v-loading="loading"
      class="lightbox-body"
      tabindex="0"
      @keydown="onKeydown"
    >
      <img v-if="src" :src="src" :alt="title || imagePath || 'preview'" class="lightbox-img" />
      <div v-else-if="failed" class="lightbox-empty">无法加载原图</div>
      <div v-else-if="!imageId && !imagePath" class="lightbox-empty">
        {{ title || '本行无图片数据' }}
      </div>
      <div v-else class="lightbox-empty">加载中…</div>
    </div>
  </el-dialog>
</template>

<style scoped>
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

.lightbox-hint {
  font-size: 12px;
  font-weight: normal;
  color: var(--el-color-primary);
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
  outline: none;
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
