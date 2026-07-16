/**
 * Sidebar menu configuration — routes and navigation.
 */
export const MENU_ITEMS = [
  {
    path: '',
    name: 'home',
    title: '首页',
    icon: 'HomeFilled',
    adminOnly: false,
    description: '系统概览与快捷入口',
  },
  {
    path: 'upload',
    name: 'upload',
    title: '图片上传',
    icon: 'UploadFilled',
    adminOnly: false,
    description: '拖拽上传、分类与标签（存储在服务器）',
  },
  {
    path: 'blob-migrate',
    name: 'blob-migrate',
    title: 'BLOB 迁移',
    icon: 'Connection',
    adminOnly: false,
    description: '从旧库 BLOB 导出到 upload 并生成路径表',
  },
  {
    path: 'blob-browse',
    name: 'blob-browse',
    title: '数据库模拟',
    icon: 'View',
    adminOnly: false,
    description: '目录、表数据、SQL 查询与多图预览',
  },
  {
    path: 'fingerprint-pairs',
    name: 'fingerprint-pairs',
    title: '指纹对比',
    icon: 'CopyDocument',
    adminOnly: false,
    description: '成对指纹入库、筛选与多层特征叠加对比',
  },
  {
    path: 'logs',
    name: 'logs',
    title: '操作日志',
    icon: 'List',
    adminOnly: true,
    description: 'SQL 执行与上传删除记录',
  },
  {
    path: 'settings',
    name: 'settings',
    title: '系统设置',
    icon: 'Setting',
    adminOnly: true,
    description: '上传限制与系统参数',
  },
]

export function filterMenuByRole(isAdmin) {
  return MENU_ITEMS.filter((item) => !item.adminOnly || isAdmin)
}

export function findMenuItemByName(name) {
  return MENU_ITEMS.find((item) => item.name === name)
}

export function findMenuItemByPath(path) {
  const normalized = path.replace(/^\//, '')
  return MENU_ITEMS.find((item) => item.path === normalized || (item.path === '' && normalized === ''))
}

export function resolveActiveMenuPath(routePath, query = {}) {
  const path = routePath.replace(/^\//, '')
  if (path === 'categories' && query.from) {
    const from = String(query.from).replace(/^\//, '')
    const parent = MENU_ITEMS.find((item) => item.path === from || item.name === from)
    if (parent) {
      return parent.path ? `/${parent.path}` : '/'
    }
  }
  if (path === 'blob-views' || path.startsWith('blob-views/') || path === 'sql-query' || path === 'sql') {
    return '/blob-browse'
  }
  if (path.startsWith('fingerprint-pairs/')) {
    return '/fingerprint-pairs'
  }
  const match = MENU_ITEMS.find((item) => {
    if (item.path === '') {
      return path === ''
    }
    return path === item.path || path.startsWith(`${item.path}/`)
  })
  return match ? (match.path ? `/${match.path}` : '/') : routePath
}
