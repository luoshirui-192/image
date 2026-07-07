import { createRouter, createWebHistory } from 'vue-router'
import { MENU_ITEMS } from '@/config/menu'
import { setupRouterGuards } from '@/router/guards'

const MainLayout = () => import('@/layouts/MainLayout.vue')
const LoginView = () => import('@/views/Login.vue')
const HomeView = () => import('@/views/Home.vue')
const PagePlaceholder = () => import('@/views/PagePlaceholder.vue')
const UploadView = () => import('@/views/Upload.vue')
const BlobMigrateView = () => import('@/views/BlobMigrate.vue')
const BlobTableViewsView = () => import('@/views/BlobTableViews.vue')
const SqlQueryView = () => import('@/views/SqlQuery.vue')
const CategoryManageView = () => import('@/views/CategoryManage.vue')
const LogsView = () => import('@/views/Logs.vue')
const SettingsView = () => import('@/views/Settings.vue')

const VIEW_MAP = {
  home: HomeView,
  upload: UploadView,
  'blob-migrate': BlobMigrateView,
  'blob-views': BlobTableViewsView,
  sql: SqlQueryView,
  categories: CategoryManageView,
  logs: LogsView,
  settings: SettingsView,
}

function buildChildRoutes() {
  const routes = MENU_ITEMS.map((item) => ({
    path: item.path,
    name: item.name,
    component: VIEW_MAP[item.name] || PagePlaceholder,
    meta: {
      title: item.title,
      icon: item.icon,
      adminOnly: item.adminOnly,
      description: item.description,
    },
  }))
  routes.push({
    path: 'sql',
    redirect: { name: 'blob-views', query: { mode: 'sql' } },
  })
  return routes
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { public: true, title: '登录' },
    },
    {
      path: '/',
      component: MainLayout,
      meta: { requiresAuth: true },
      children: buildChildRoutes(),
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

setupRouterGuards(router)

export default router

export function getMenuRoutes() {
  return MENU_ITEMS
}
