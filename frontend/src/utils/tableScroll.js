import { nextTick } from 'vue'

/**
 * Highlight a table row and optionally scroll it into a viewport.
 *
 * @param {import('vue').Ref} tableRef el-table ref
 * @param {object|null} row
 * @param {(a: object, b: object) => boolean} [matchFn]
 * @param {{ scroll?: boolean, scrollParent?: HTMLElement|null }} [options]
 *   - scroll: default true; set false on mouse click (row already visible)
 *   - scrollParent: outer overflow container (preferred). Avoids el.scrollIntoView
 *     which can scroll ancestor panels / reset to top.
 */
export function highlightAndScrollTableRow(tableRef, row, matchFn, options = {}) {
  const scroll = options.scroll !== false
  const scrollParent = options.scrollParent || null

  nextTick(() => {
    const table = tableRef?.value
    if (!table) return

    table.setCurrentRow(row ?? undefined)
    if (!row || !scroll) return

    nextTick(() => {
      scrollRowIntoView(table, row, matchFn, scrollParent)
    })
  })
}

function getTableData(table) {
  return table.store?.states?.data?.value || table.data || []
}

function getMainBodyRows(table) {
  const bodyWrapper = table.$refs?.bodyWrapper
  if (!bodyWrapper) return { scrollWrap: null, rows: [] }

  const scrollWrap = bodyWrapper.querySelector('.el-scrollbar__wrap') || bodyWrapper
  const rows = scrollWrap.querySelectorAll('tbody tr.el-table__row')
  return { scrollWrap, rows }
}

function adjustScrollParentToRow(scrollParent, target) {
  if (!scrollParent || !target) return
  const wrapRect = scrollParent.getBoundingClientRect()
  const rowRect = target.getBoundingClientRect()
  let nextTop = scrollParent.scrollTop

  if (rowRect.top < wrapRect.top) {
    nextTop += rowRect.top - wrapRect.top - 8
  } else if (rowRect.bottom > wrapRect.bottom) {
    nextTop += rowRect.bottom - wrapRect.bottom + 8
  } else {
    return
  }
  scrollParent.scrollTop = Math.max(0, nextTop)
}

function scrollRowIntoView(table, row, matchFn, scrollParent) {
  const data = getTableData(table)
  let index = data.indexOf(row)
  if (index < 0 && matchFn) {
    index = data.findIndex((item) => matchFn(item, row))
  }
  if (index < 0) return

  const { scrollWrap, rows } = getMainBodyRows(table)
  const target = rows[index]
  if (!target) return

  // Prefer the explicit outer viewport (browse/SQL list scroll).
  if (scrollParent) {
    adjustScrollParentToRow(scrollParent, target)
    return
  }

  if (scrollWrap && scrollWrap.scrollHeight > scrollWrap.clientHeight + 1) {
    adjustScrollParentToRow(scrollWrap, target)
    return
  }

  // Last resort: only nudge nearest without smooth ancestor jumps when possible.
  adjustScrollParentToRow(scrollWrap, target)
}
