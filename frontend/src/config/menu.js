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
    path: 'import',
    name: 'import',
    title: '批量导入',
    icon: 'FolderOpened',
    adminOnly: true,
    description: '扫描目录批量导入图片',
  },
  {
    path: 'sql',
    name: 'sql',
    title: 'SQL 查询',
    icon: 'Document',
    adminOnly: true,
    description: '自定义 SELECT 查询与图片预览',
  },
  {
    path: 'images',
    name: 'images',
    title: '图片列表',
    icon: 'PictureFilled',
    adminOnly: false,
    description: '预览、下载服务器上的图片',
  },
  {
    path: 'categories',
    name: 'categories',
    title: '分类管理',
    icon: 'Menu',
    adminOnly: true,
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
