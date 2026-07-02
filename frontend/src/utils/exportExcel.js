import * as XLSX from 'xlsx'
import { formatCellValue } from '@/api/sql'

export function exportSqlResultToExcel(columns, rows, filename = 'sql_result.xlsx') {
  const header = columns.map(String)
  const body = rows.map((row) => row.map((cell) => formatCellValue(cell)))
  const sheet = XLSX.utils.aoa_to_sheet([header, ...body])

  const colWidths = header.map((col, colIndex) => {
    const maxLen = Math.max(
      col.length,
      ...body.map((row) => String(row[colIndex] ?? '').length),
    )
    return { wch: Math.min(Math.max(maxLen + 2, 8), 48) }
  })
  sheet['!cols'] = colWidths

  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, sheet, 'QueryResult')
  XLSX.writeFile(workbook, filename)
}
