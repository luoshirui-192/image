import request from './request'

function appendSimulateContext(payload, context = {}) {
  if (context.dbAlias) payload.db_alias = context.dbAlias
  if (context.connectionId != null) payload.connection_id = context.connectionId
  if (context.database) payload.database = context.database
  if (context.viewId != null) payload.view_id = context.viewId
  if (context.sourceTable) payload.source_table = context.sourceTable
  if (context.sourcePkColumn) payload.source_pk_column = context.sourcePkColumn
  if (context.blobColumns?.length) payload.blob_columns = context.blobColumns
  if (context.sourceObjectType) payload.source_object_type = context.sourceObjectType
  if (context.pathLookupTable) payload.path_lookup_table = context.pathLookupTable
  if (context.blobMode) payload.blob_mode = context.blobMode
  return payload
}

export function executeSqlApi(sql, context = {}) {
  return request.post('/sql/execute/', appendSimulateContext({ sql }, context), { timeout: 60000 })
}

export function validateSqlApi(sql, context = {}) {
  return request.post('/sql/validate/', appendSimulateContext({ sql }, context))
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

/** Path cell object from simulated SQL / table browse API. */
export function isPathCellValue(value) {
  return value != null && typeof value === 'object' && 'display' in value
}

export function pathCellDisplay(value) {
  if (isPathCellValue(value)) return value.display || '—'
  if (value == null) return '—'
  return String(value)
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
  if (value == null) return '—'
  if (isPathCellValue(value)) return value.display || '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function sqlColumnMetaMap(columnMeta = []) {
  const map = {}
  for (const item of columnMeta || []) {
    if (item?.name) map[item.name] = item
  }
  return map
}
