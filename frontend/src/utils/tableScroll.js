import { nextTick } from 'vue'

/**
 * Highlight a table row and scroll it into the visible viewport.
 */
export function highlightAndScrollTableRow(tableRef, row, matchFn) {
  nextTick(() => {
    const table = tableRef?.value
    if (!table) return

    table.setCurrentRow(row ?? undefined)
    if (!row) return

    nextTick(() => {
      scrollRowIntoView(table, row, matchFn)
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

function scrollRowIntoView(table, row, matchFn) {
  const data = getTableData(table)
  let index = data.indexOf(row)
  if (index < 0 && matchFn) {
    index = data.findIndex((item) => matchFn(item, row))
  }
  if (index < 0) return

  const { scrollWrap, rows } = getMainBodyRows(table)
  const target = rows[index]
  if (!target) return

  if (scrollWrap && scrollWrap.scrollHeight > scrollWrap.clientHeight + 1) {
    const wrapRect = scrollWrap.getBoundingClientRect()
    const rowRect = target.getBoundingClientRect()
    let nextTop = scrollWrap.scrollTop

    if (rowRect.top < wrapRect.top) {
      nextTop += rowRect.top - wrapRect.top - 8
    } else if (rowRect.bottom > wrapRect.bottom) {
      nextTop += rowRect.bottom - wrapRect.bottom + 8
    } else {
      return
    }

    scrollWrap.scrollTo({ top: Math.max(0, nextTop), behavior: 'smooth' })
    return
  }

  target.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}
