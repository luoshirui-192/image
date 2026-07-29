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
    const requestOnce = () => fetch(`${API_BASE}${endpoint}?${params}`, {
      headers: {
        Authorization: `Bearer ${auth.accessToken}`,
      },
      signal,
    })

    let res = await requestOnce()
    if (res.status === 401 && auth.refreshToken) {
      try {
        await auth.refreshAccessToken()
        res = await requestOnce()
      } catch {
        auth.logout()
        throw new Error('登录已过期，请重新登录')
      }
    } else if (res.status === 401) {
      auth.logout()
      throw new Error('登录已过期，请重新登录')
    }

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

export function listBlobMigrationSourcesApi({ includeStats = false } = {}) {
  return request.get('/images/blob-migration/sources/', {
    params: { include_stats: includeStats ? 1 : 0 },
    timeout: includeStats ? 120000 : 30000,
  })
}

export function listBlobMigrationMapStatsApi() {
  return request.get('/images/blob-migration/map-stats/', { timeout: 60000 })
}

export function createBlobMigrationSourceApi(data, { includeStats = false } = {}) {
  return request.post('/images/blob-migration/sources/', data, {
    params: { include_stats: includeStats ? 1 : 0 },
    timeout: includeStats ? 120000 : 60000,
  })
}

export function getBlobMigrationSourceApi(id, { includeStats = false } = {}) {
  return request.get(`/images/blob-migration/sources/${id}/`, {
    params: { include_stats: includeStats ? 1 : 0 },
    timeout: includeStats ? 120000 : 30000,
  })
}

export function deleteBlobMigrationSourceApi(id) {
  return request.delete(`/images/blob-migration/sources/${id}/`)
}

export function runGlobalDataSyncApi(data = {}) {
  return request.post('/images/blob-migration/sync/backfill/', data, { timeout: 600000 })
}

export function runBlobMigrationApi({ sourceId, batchSize = 50, dryRun = false, skipExisting = true }) {
  return request.post('/images/blob-migration/run/', {
    source_id: sourceId,
    batch_size: batchSize,
    dry_run: dryRun,
    skip_existing: skipExisting,
  }, { timeout: 600000, skipGlobalError: true })
}

export function getBlobMigrationSourceSchemaCheckApi(id) {
  return request.get(`/images/blob-migration/sources/${id}/schema-check/`, { timeout: 60000 })
}

export function rebindBlobMigrationSourceApi(id, data) {
  return request.post(`/images/blob-migration/sources/${id}/rebind/`, data, { timeout: 120000 })
}

export function linkBlobTableViewSourceApi(viewId, { sourceUid }) {
  return request.post(`/images/blob-migration/table-views/${viewId}/link-source/`, {
    source_uid: sourceUid,
  }, { timeout: 60000 })
}

export function listBlobMigrationJobsApi({ sourceId } = {}) {
  const params = sourceId != null ? { source_id: sourceId } : undefined
  return request.get('/images/blob-migration/jobs/', { params, timeout: 60000 })
}

export function createBlobMigrationJobApi({
  sourceId,
  batchSize = 50,
  dryRun = false,
  skipExisting = true,
  runAll = true,
  warmThumbsAfter = true,
}) {
  return request.post('/images/blob-migration/jobs/', {
    source_id: sourceId,
    batch_size: batchSize,
    dry_run: dryRun,
    skip_existing: skipExisting,
    run_all: runAll,
    warm_thumbs_after: warmThumbsAfter,
  }, { timeout: 120000 })
}

export function getBlobMigrationJobApi(jobId) {
  return request.get(`/images/blob-migration/jobs/${jobId}/`, { timeout: 120000 })
}

export function deleteBlobMigrationJobApi(jobId) {
  return request.delete(`/images/blob-migration/jobs/${jobId}/`)
}

export function clearBlobMigrationJobHistoryApi({ sourceId } = {}) {
  const payload = {}
  if (sourceId != null) {
    payload.source_id = sourceId
  }
  return request.post('/images/blob-migration/jobs/clear/', payload)
}

export function cancelBlobMigrationJobApi(jobId) {
  return request.post(`/images/blob-migration/jobs/${jobId}/cancel/`)
}

export function pauseBlobMigrationJobApi(jobId) {
  return request.post(`/images/blob-migration/jobs/${jobId}/pause/`)
}

export function resumeBlobMigrationJobApi(jobId) {
  return request.post(`/images/blob-migration/jobs/${jobId}/resume/`)
}

export function retryBlobMigrationJobApi({ parentJobId, batchSize = 50, dryRun = false, warmThumbsAfter = true }) {
  return request.post('/images/blob-migration/jobs/retry/', {
    parent_job_id: parentJobId,
    batch_size: batchSize,
    dry_run: dryRun,
    warm_thumbs_after: warmThumbsAfter,
  })
}

export function exportBlobMigrationJobErrorsUrl(jobId) {
  const base = import.meta.env.VITE_API_BASE_URL || '/api'
  return `${base}/images/blob-migration/jobs/${jobId}/errors/export/`
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

export function provisionExternalDbTableViewsApi(id) {
  return request.post(`/images/blob-migration/connections/${id}/provision-table-views/`, {}, { timeout: 600000 })
}

export function listBlobCatalogConnectionsApi() {
  return request.get('/images/blob-catalog/connections/')
}

export function listBlobCatalogDatabasesApi({ connectionId, dbAlias } = {}) {
  const params = {}
  if (connectionId != null) params.connection_id = connectionId
  if (dbAlias) params.db_alias = dbAlias
  return request.get('/images/blob-catalog/databases/', { params })
}

export function listBlobCatalogObjectsApi({ connectionId, dbAlias, database, objectType } = {}) {
  const params = { database }
  if (connectionId != null) params.connection_id = connectionId
  if (dbAlias) params.db_alias = dbAlias
  if (objectType) params.object_type = objectType
  return request.get('/images/blob-catalog/objects/', { params })
}

export function getBlobCatalogObjectApi(name, { connectionId, dbAlias, database } = {}) {
  const params = { database }
  if (connectionId != null) params.connection_id = connectionId
  if (dbAlias) params.db_alias = dbAlias
  return request.get(`/images/blob-catalog/objects/${encodeURIComponent(name)}/`, { params })
}

export function listBlobTableViewsApi() {
  return request.get('/images/blob-migration/table-views/', { timeout: 120000 })
}

export function createBlobTableViewApi(data) {
  return request.post('/images/blob-migration/table-views/', data, { timeout: 120000 })
}

export function updateBlobTableViewApi(id, data) {
  return request.patch(`/images/blob-migration/table-views/${id}/`, data)
}

export function deleteBlobTableViewApi(id) {
  return request.delete(`/images/blob-migration/table-views/${id}/`)
}

export function fetchBlobTableViewRowsApi(id, {
  offset = 0,
  limit = 100,
  includeTotal = false,
  skipBlobPresence = true,
  afterPk = null,
} = {}) {
  const params = {
    offset,
    limit,
    include_total: includeTotal ? 1 : 0,
    skip_blob_presence: skipBlobPresence ? 1 : 0,
  }
  if (afterPk != null && String(afterPk) !== '') {
    params.after_pk = String(afterPk)
  }
  return request.get(`/images/blob-migration/table-views/${id}/rows/`, {
    params,
    timeout: 120000,
  })
}

export function fetchBlobTableViewRowCountApi(id) {
  return request.get(`/images/blob-migration/table-views/${id}/row-count/`, {
    timeout: 120000,
  })
}

export function exportBlobTableViewToConnectionApi(id, data) {
  // Starts a background job (avoids gateway 504 on long sync exports).
  return request.post(`/images/blob-browse/${id}/export-to-connection/`, data, { timeout: 60000 })
}

export function listBlobSimulatedExportJobsApi({ activeOnly = false, limit = 50 } = {}) {
  return request.get('/images/blob-browse/export-jobs/', {
    params: {
      active_only: activeOnly ? 1 : 0,
      limit,
    },
  })
}

export function getBlobSimulatedExportJobApi(jobId) {
  return request.get(`/images/blob-browse/export-jobs/${jobId}/`)
}

export function cancelBlobSimulatedExportJobApi(jobId) {
  return request.post(`/images/blob-browse/export-jobs/${jobId}/`, { action: 'cancel' })
}

export function pauseBlobSimulatedExportJobApi(jobId) {
  return request.post(`/images/blob-browse/export-jobs/${jobId}/`, { action: 'pause' })
}

export function resumeBlobSimulatedExportJobApi(jobId) {
  return request.post(`/images/blob-browse/export-jobs/${jobId}/`, { action: 'resume' })
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
