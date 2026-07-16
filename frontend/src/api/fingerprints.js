import request from './request'

export function fetchFingerprintMetaApi() {
  return request.get('/fingerprints/meta/')
}

export function fetchFingerprintLayerTypesApi(params = {}) {
  return request.get('/fingerprints/layer-types/', { params })
}

export function createFingerprintLayerTypeApi(data) {
  return request.post('/fingerprints/layer-types/', data)
}

export function fetchFingerprintPairsApi(params = {}) {
  return request.get('/fingerprints/pairs/', { params })
}

export function fetchFingerprintPairApi(id) {
  return request.get(`/fingerprints/pairs/${id}/`)
}

export function deleteFingerprintPairApi(id) {
  return request.delete(`/fingerprints/pairs/${id}/`)
}

export function fetchFingerprintCompareApi(id, params = {}) {
  return request.get(`/fingerprints/pairs/${id}/compare/`, { params })
}

export function importFingerprintZipApi(file, { tags, algo_version, skip_existing, category_id, onUploadProgress } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (tags) form.append('tags', tags)
  if (algo_version) form.append('algo_version', algo_version)
  if (skip_existing != null) form.append('skip_existing', skip_existing ? '1' : '0')
  if (category_id != null) form.append('category_id', String(category_id))
  return request.post('/fingerprints/pairs/import-zip/', form, {
    onUploadProgress,
    timeout: 300000,
  })
}

export function importFingerprintFilesApi(files, { batch_name, match_score, tags, algo_version, category_id } = {}) {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  if (batch_name) form.append('batch_name', batch_name)
  if (match_score != null && match_score !== '') form.append('match_score', String(match_score))
  if (tags) form.append('tags', tags)
  if (algo_version) form.append('algo_version', algo_version)
  if (category_id != null) form.append('category_id', String(category_id))
  return request.post('/fingerprints/pairs/import/', form, { timeout: 300000 })
}
