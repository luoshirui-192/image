/**
 * Map SQL execute result rows into fingerprint browse list items.
 */

function cellToString(value) {
  if (value == null) return ''
  if (typeof value === 'object' && value !== null && 'display' in value) {
    return String(value.display ?? '').trim()
  }
  return String(value).trim()
}

function lowerKeyMap(columns = []) {
  const map = new Map()
  columns.forEach((name, idx) => {
    map.set(String(name).toLowerCase(), idx)
  })
  return map
}

function pick(row, keyMap, aliases) {
  for (const alias of aliases) {
    const idx = keyMap.get(alias.toLowerCase())
    if (idx == null) continue
    const text = cellToString(row[idx])
    if (text) return text
  }
  return ''
}

function pairSqlKey(imageReg, imageMatch) {
  return `${imageReg}\u0001${imageMatch}`
}

/**
 * @param {'pair'|'single'} mode
 * @param {string[]} columns
 * @param {any[][]} rows
 * @returns {{ items: object[], skipped: number, error?: string }}
 */
export function mapSqlResultToBrowseRows(mode, columns, rows) {
  const keyMap = lowerKeyMap(columns)
  const items = []
  let skipped = 0

  if (mode === 'pair') {
    const hasId = keyMap.has('id') || keyMap.has('match_id')
    const hasReg = [...keyMap.keys()].some((k) =>
      ['image_reg', 'reg', 'reg_image', 'image_reg_id'].includes(k),
    )
    const hasMatch = [...keyMap.keys()].some((k) =>
      ['image_match', 'match', 'match_image', 'image_match_id'].includes(k),
    )
    if (!hasId && !(hasReg && hasMatch)) {
      return {
        items: [],
        skipped: 0,
        error:
          'SQL 结果需包含 id，或同时包含 image_reg 与 image_match（可用别名 reg/match）',
      }
    }

    for (const row of rows || []) {
      const idRaw = pick(row, keyMap, ['id', 'match_id'])
      let id = null
      if (idRaw !== '') {
        const n = Number(idRaw)
        if (!Number.isNaN(n)) id = n
      }
      const image_reg = pick(row, keyMap, ['image_reg', 'reg', 'reg_image', 'image_reg_id'])
      const image_match = pick(row, keyMap, [
        'image_match',
        'match',
        'match_image',
        'image_match_id',
      ])
      const data_set_code = pick(row, keyMap, ['data_set_code', 'dataset_code', 'dataset'])
      if (id == null && (!image_reg || !image_match)) {
        skipped += 1
        continue
      }
      const sqlKey = image_reg && image_match ? pairSqlKey(image_reg, image_match) : `id:${id}`
      items.push({
        id,
        image_reg,
        image_match,
        data_set_code: data_set_code || 'SQL',
        _sqlKey: sqlKey,
        _fromSql: true,
      })
    }
    return { items, skipped }
  }

  // single
  const hasCap = [...keyMap.keys()].some((k) =>
    ['cap_image_id', 'cap_id', 'image_id', 'fp_image_id'].includes(k),
  )
  if (!hasCap) {
    return {
      items: [],
      skipped: 0,
      error: 'SQL 结果需包含 cap_image_id（可用别名 cap_id / image_id / fp_image_id）',
    }
  }
  for (const row of rows || []) {
    const cap_image_id = pick(row, keyMap, [
      'cap_image_id',
      'cap_id',
      'image_id',
      'fp_image_id',
    ])
    if (!cap_image_id) {
      skipped += 1
      continue
    }
    const dataset_code = pick(row, keyMap, ['dataset_code', 'data_set_code', 'dataset'])
    items.push({
      cap_image_id,
      dataset_code: dataset_code || 'SQL',
      _fromSql: true,
    })
  }
  return { items, skipped }
}

export function defaultBrowseSql(mode) {
  if (mode === 'pair') {
    return [
      'SELECT id, image_reg, image_match, data_set_code',
      'FROM t_match_result_image',
      "WHERE data_set_code = 'PK_5W'",
      'LIMIT 200',
    ].join('\n')
  }
  return [
    'SELECT cap_image_id, dataset_code',
    'FROM T_CAP_FP_DATA',
    "WHERE dataset_code = 'PK_5W'",
    'LIMIT 200',
  ].join('\n')
}

export { pairSqlKey }
