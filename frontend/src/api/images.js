import { useAuthStore } from '@/stores/auth'
import request from './request'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

const blobCache = new Map()
const inflight = new Map()

function cacheKey(path, { id, thumb }) {
  return `${thumb ? 't' : 'f'}:${id ?? ''}:${path ?? ''}`
}

/** Fetch binary image with JWT (for img preview — cannot use plain src). */
export async function fetchImageBlob(path, { id, thumb = true, signal } = {}) {
  const key = cacheKey(path, { id, thumb })
  if (blobCache.has(key)) {
    return blobCache.get(key)
  }
  if (inflight.has(key)) {
    return inflight.get(key)
  }

  const auth = useAuthStore()
  const endpoint = thumb ? '/images/thumb/' : '/images/file/'
  const params = new URLSearchParams()
  if (id != null) {
    params.set('id', String(id))
  } else if (path) {
    params.set('path', path)
  } else {
    throw new Error('需要 id 或 path')
  }

  const task = (async () => {
    const res = await fetch(`${API_BASE}${endpoint}?${params}`, {
      headers: {
        Authorization: `Bearer ${auth.accessToken}`,
      },
      signal,
    })

    if (!res.ok) {
      let message = '图片加载失败'
      try {
        const json = await res.json()
        message = json.message || message
      } catch {
        // ignore
      }
      throw new Error(message)
    }

    const blob = await res.blob()
    blobCache.set(key, blob)
    return blob
  })()

  inflight.set(key, task)
  try {
    return await task
  } finally {
    inflight.delete(key)
  }
}

export function clearImageBlobCache() {
  blobCache.clear()
  inflight.clear()
}

export function listCategoriesApi() {
  return request.get('/images/categories/')
}

export function uploadImagesApi(files, { categoryId, tags, overwrite = false } = {}) {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  if (categoryId != null && categoryId !== '') {
    form.append('category_id', String(categoryId))
  }
  if (tags) {
    form.append('tags', tags)
  }
  if (overwrite) {
    form.append('overwrite', 'true')
  }
  return request.post('/images/upload/', form, { timeout: 120000, skipGlobalError: true })
}

export function listBlobMigrationDatabasesApi() {
  return request.get('/images/blob-migration/databases/')
}

export function discoverBlobTablesApi({ dbAlias = 'default' } = {}) {
  return request.post('/images/blob-migration/discover/', { db_alias: dbAlias })
}

export function listBlobMigrationSourcesApi() {
  return request.get('/images/blob-migration/sources/')
}

export function createBlobMigrationSourceApi(data) {
  return request.post('/images/blob-migration/sources/', data)
}

export function deleteBlobMigrationSourceApi(id) {
  return request.delete(`/images/blob-migration/sources/${id}/`)
}

export function runBlobMigrationApi({ sourceId, batchSize = 50, dryRun = false, skipExisting = true }) {
  return request.post('/images/blob-migration/run/', {
    source_id: sourceId,
    batch_size: batchSize,
    dry_run: dryRun,
    skip_existing: skipExisting,
  }, { timeout: 600000, skipGlobalError: true })
}

export function listExternalDbConnectionsApi() {
  return request.get('/images/blob-migration/connections/')
}

export function createExternalDbConnectionApi(data) {
  return request.post('/images/blob-migration/connections/', data)
}

export function updateExternalDbConnectionApi(id, data) {
  return request.patch(`/images/blob-migration/connections/${id}/`, data)
}

export function deleteExternalDbConnectionApi(id) {
  return request.delete(`/images/blob-migration/connections/${id}/`)
}

export function testExternalDbConnectionApi(data) {
  return request.post('/images/blob-migration/connections/test/', data, { skipGlobalError: true })
}

export function testSavedExternalDbConnectionApi(id, data = {}) {
  return request.post(`/images/blob-migration/connections/${id}/test/`, data, { skipGlobalError: true })
}

export function listBlobTableViewsApi() {
  return request.get('/images/blob-migration/table-views/')
}

export function createBlobTableViewApi(data) {
  return request.post('/images/blob-migration/table-views/', data)
}

export function updateBlobTableViewApi(id, data) {
  return request.patch(`/images/blob-migration/table-views/${id}/`, data)
}

export function deleteBlobTableViewApi(id) {
  return request.delete(`/images/blob-migration/table-views/${id}/`)
}

export function fetchBlobTableViewRowsApi(id, { offset = 0, limit = 100 } = {}) {
  return request.get(`/images/blob-migration/table-views/${id}/rows/`, {
    params: { offset, limit },
    timeout: 120000,
  })
}

export function getBlobTableViewSchemaApi(id) {
  return request.get(`/images/blob-migration/table-views/${id}/schema/`)
}

export function previewBlobTableViewSchemaApi(data) {
  return request.post('/images/blob-migration/table-views/preview-schema/', data)
}

export function formatFileSize(bytes) {
  if (bytes == null || bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = Number(bytes)
  let i = 0
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i += 1
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export function formatDateTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString('zh-CN', { hour12: false })
}

export function formatDeletionRemaining(deletionInfo) {
  if (!deletionInfo) return '—'
  if (deletionInfo.expired) return '已超过保留期'
  const days = deletionInfo.days_remaining ?? 0
  const hours = deletionInfo.hours_remaining ?? 0
  if (days > 0) {
    return hours > 0 ? `${days} 天 ${hours} 小时` : `${days} 天`
  }
  if (hours > 0) return `${hours} 小时`
  return '不足 1 小时'
}

export function getImageApi(id) {
  return request.get(`/images/${id}/`)
}

export function updateImageApi(id, data) {
  return request.patch(`/images/${id}/`, data)
}

export function deleteImageApi(id) {
  return request.delete(`/images/${id}/`)
}

export function restoreImageApi(id) {
  return request.post(`/images/${id}/restore/`)
}

export function createCategoryApi(data) {
  return request.post('/images/categories/', data)
}

export function updateCategoryApi(id, data) {
  return request.patch(`/images/categories/${id}/`, data)
}

export function deleteCategoryApi(id) {
  return request.delete(`/images/categories/${id}/`)
}

export async function downloadImageFile({ id, path, filename = 'image.jpg' }) {
  const auth = useAuthStore()
  const params = new URLSearchParams()
  if (id != null) {
    params.set('id', String(id))
  } else if (path) {
    params.set('path', path)
  } else {
    throw new Error('需要 id 或 path')
  }

  const res = await fetch(`${API_BASE}/images/download/?${params}`, {
    headers: { Authorization: `Bearer ${auth.accessToken}` },
  })

  if (!res.ok) {
    let message = '下载失败'
    try {
      const json = await res.json()
      message = json.message || message
    } catch {
      // ignore
    }
    throw new Error(message)
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
