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
    path: 'blob-views',
    name: 'blob-views',
    title: 'BLOB 表视图',
    icon: 'View',
    adminOnly: false,
    description: '浏览远程旧表，BLOB 列显示为本地路径',
  },
  {
    path: 'sql',
    name: 'sql',
    title: 'SQL 查询',
    icon: 'Document',
    adminOnly: false,
    description: '自定义 SELECT 查询与图片预览',
  },
  {
    path: 'categories',
    name: 'categories',
    title: '分类管理',
    icon: 'Menu',
    adminOnly: false,
    description: '维护图片分类',
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

export function resolveActiveMenuPath(routePath) {
  const path = routePath.replace(/^\//, '')
  const match = MENU_ITEMS.find((item) => {
    if (item.path === '') {
      return path === ''
    }
    return path === item.path || path.startsWith(`${item.path}/`)
  })
  return match ? (match.path ? `/${match.path}` : '/') : routePath
}
