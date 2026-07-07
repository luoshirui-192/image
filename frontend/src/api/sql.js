import request from './request'

export function executeSqlApi(sql, context = {}) {
  const payload = { sql }
  if (context.dbAlias) payload.db_alias = context.dbAlias
  if (context.connectionId != null) payload.connection_id = context.connectionId
  if (context.database) payload.database = context.database
  return request.post('/sql/execute/', payload, { timeout: 60000 })
}

export function validateSqlApi(sql, context = {}) {
  const payload = { sql }
  if (context.dbAlias) payload.db_alias = context.dbAlias
  if (context.connectionId != null) payload.connection_id = context.connectionId
  if (context.database) payload.database = context.database
  return request.post('/sql/validate/', payload)
}

export function listSqlTemplatesApi() {
  return request.get('/sql/templates/')
}

export function saveSqlTemplateApi(name, sql) {
  return request.post('/sql/templates/', { name, sql })
}

/** Column names that hold image storage paths. */
export const PATH_COLUMN_NAMES = [
  'image_path',
  'save_path',
  'path',
  'file_path',
  'img_path',
  'storage_path',
  'filepath',
]

const IMAGE_EXT_PATTERN = /\.(jpe?g|png|gif|webp|bmp)$/i

/** Whether a cell value looks like an upload-relative image path. */
export function isImagePathValue(value) {
  if (value == null || value === '') return false
  const text = String(value).trim().replace(/\\/g, '/')
  if (!text.startsWith('upload/')) return false
  return IMAGE_EXT_PATTERN.test(text)
}

/**
 * Find the column that holds image paths.
 * 1) Match known column names; 2) match names containing "path";
 * 3) infer from cell values (e.g. aliased columns).
 */
export function findPathColumn(columns = [], rows = []) {
  if (!columns.length) return null
  const lower = columns.map((c) => String(c).toLowerCase())

  for (const name of PATH_COLUMN_NAMES) {
    const idx = lower.indexOf(name)
    if (idx >= 0) return columns[idx]
  }

  const partialIdx = lower.findIndex((c) => c.includes('path') || c.includes('filepath'))
  if (partialIdx >= 0) {
    const col = columns[partialIdx]
    if (!rows.length || rows.some((row) => isImagePathValue(row[partialIdx]))) {
      return col
    }
  }

  const sampleSize = Math.min(rows.length, 8)
  if (sampleSize === 0) return null

  let bestIdx = -1
  let bestHits = 0
  for (let i = 0; i < columns.length; i += 1) {
    let hits = 0
    for (let r = 0; r < sampleSize; r += 1) {
      if (isImagePathValue(rows[r]?.[i])) hits += 1
    }
    if (hits > bestHits) {
      bestHits = hits
      bestIdx = i
    }
  }
  if (bestIdx >= 0 && bestHits >= Math.ceil(sampleSize * 0.5)) {
    return columns[bestIdx]
  }

  return null
}

export function rowsToRecords(columns, rows) {
  return rows.map((row) => {
    const record = {}
    columns.forEach((col, index) => {
      record[col] = row[index]
    })
    return record
  })
}

export function formatCellValue(value) {
  if (value == null) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
