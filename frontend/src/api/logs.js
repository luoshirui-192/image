import request from './request'

export const LOG_ACTION_TYPES = [
  { value: 'login', label: '登录' },
  { value: 'upload', label: '上传' },
  { value: 'import', label: '批量导入' },
  { value: 'sql_execute', label: 'SQL 执行' },
  { value: 'image_update', label: '图片更新' },
  { value: 'image_delete', label: '图片删除' },
  { value: 'image_batch_delete', label: '批量删除' },
  { value: 'image_restore', label: '图片恢复' },
  { value: 'category_create', label: '创建分类' },
  { value: 'category_update', label: '更新分类' },
  { value: 'category_delete', label: '删除分类' },
]

export function actionTypeLabel(value) {
  return LOG_ACTION_TYPES.find((item) => item.value === value)?.label || value
}

export function listLogsApi(params = {}) {
  return request.get('/logs/', { params })
}

export function fetchStorageStatsApi() {
  return request.get('/logs/stats/')
}
