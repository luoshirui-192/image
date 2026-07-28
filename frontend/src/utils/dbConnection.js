/**
 * Shared helpers for catalog / fingerprint connection keys and API query params.
 */

/** Stable key for <select> / route query: ext:12 or alias:default */
export function connectionKey(conn) {
  if (!conn) return ''
  if (conn.connection_id != null) return `ext:${conn.connection_id}`
  return `alias:${conn.alias || 'default'}`
}

/** Prefer connections whose label/alias/name mentions "ara". */
export function pickPreferredConnection(connections, { preferAra = true } = {}) {
  const list = Array.isArray(connections) ? connections : []
  if (!list.length) return null
  if (preferAra) {
    const preferred = list.find(
      (c) =>
        String(c.label || c.alias || '')
          .toLowerCase()
          .includes('ara') || String(c.name || '').toLowerCase().includes('ara'),
    )
    if (preferred) return preferred
  }
  return list[0]
}

/**
 * Query params for fingerprint biz APIs (pairs / eval / path writeback).
 * Default database is ara_fp_analyst; local default alias clears database for sqlite/same-DB.
 */
export function connectionQueryParams(conn, { database = 'ara_fp_analyst' } = {}) {
  if (!conn) return null
  const params = { database }
  if (conn.connection_id != null) {
    params.connection_id = conn.connection_id
  } else {
    params.db_alias = conn.alias || 'default'
    if (!conn.connection_id && (conn.alias === 'default' || !conn.alias)) {
      params.database = ''
    }
  }
  return params
}
