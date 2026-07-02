<script setup>

import { onMounted, onUnmounted, ref, watch } from 'vue'

import { Picture } from '@element-plus/icons-vue'

import { fetchImageBlob } from '@/api/images'



const props = defineProps({

  imageId: { type: Number, default: null },

  imagePath: { type: String, default: '' },

  size: { type: Number, default: 80 },

  fit: { type: String, default: 'cover' },

  thumb: { type: Boolean, default: true },

  clickable: { type: Boolean, default: false },

  lazy: { type: Boolean, default: true },

})



const emit = defineEmits(['click'])



const rootRef = ref(null)

const src = ref('')

const loading = ref(false)

const failed = ref(false)

const visible = ref(!props.lazy)

let objectUrl = ''

let abortController = null

let observer = null



function revokeObjectUrl() {

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

    const blob = await fetchImageBlob(props.imagePath, {

      id: props.imageId,

      thumb: props.thumb,

      signal,

    })

    if (signal.aborted) return

    objectUrl = URL.createObjectURL(blob)

    src.value = objectUrl

  } catch (err) {

    if (signal.aborted) return

    failed.value = true

  } finally {

    if (!signal.aborted) {

      loading.value = false

    }

  }

}



function setupObserver() {

  if (!props.lazy || typeof IntersectionObserver === 'undefined') {

    visible.value = true

    return

  }

  observer = new IntersectionObserver(

    (entries) => {

      if (entries.some((entry) => entry.isIntersecting)) {

        visible.value = true

        observer?.disconnect()

        observer = null

        loadPreview()

      }

    },

    { rootMargin: '120px' },

  )

  if (rootRef.value) {

    observer.observe(rootRef.value)

  }

}



watch(

  () => [props.imageId, props.imagePath, props.thumb, visible.value],

  () => {

    if (visible.value) {

      loadPreview()

    }

  },

)



watch(

  () => props.lazy,

  (lazy) => {

    if (!lazy) {

      visible.value = true

      observer?.disconnect()

      observer = null

      loadPreview()

    }

  },

)



onMounted(() => {

  if (props.lazy) {

    setupObserver()

  } else {

    loadPreview()

  }

})



onUnmounted(() => {

  observer?.disconnect()

  abortPending()

  revokeObjectUrl()

})

</script>



<template>

  <div

    ref="rootRef"

    class="image-preview"

    :class="{ clickable }"

    :style="{ width: `${size}px`, height: `${size}px` }"

    v-loading="loading"

    @click="clickable && emit('click')"

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

  </div>

</template>



<style scoped>

.image-preview {

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

</style>


