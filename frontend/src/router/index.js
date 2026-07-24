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
const FingerprintPairsView = () => import('@/views/FingerprintPairs.vue')
const FingerprintCompareView = () => import('@/views/FingerprintCompare.vue')
const FingerprintEvalView = () => import('@/views/FingerprintEval.vue')
const CategoryManageView = () => import('@/views/CategoryManage.vue')
const LogsView = () => import('@/views/Logs.vue')
const SettingsView = () => import('@/views/Settings.vue')

const VIEW_MAP = {
  home: HomeView,
  upload: UploadView,
  'blob-migrate': BlobMigrateView,
  'blob-browse': BlobTableViewsView,
  'fingerprint-pairs': FingerprintPairsView,
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
  routes.push(
    {
      path: 'categories',
      name: 'categories',
      component: CategoryManageView,
      meta: {
        title: '分类管理',
        hiddenInMenu: true,
      },
    },
    {
      path: 'fingerprint-pairs/:id/compare',
      name: 'fingerprint-compare',
      component: FingerprintCompareView,
      meta: {
        title: '指纹对比详情',
        hiddenInMenu: true,
      },
      props: true,
    },
    {
      path: 'fingerprint-eval',
      name: 'fingerprint-eval',
      component: FingerprintEvalView,
      meta: {
        title: '指纹评测指标',
        hiddenInMenu: true,
      },
    },
    {
      path: 'blob-views',
      redirect: (to) => ({ name: 'blob-browse', query: to.query, hash: to.hash }),
    },
    {
      path: 'sql-query',
      redirect: { name: 'blob-browse', query: { mode: 'sql' } },
    },
    {
      path: 'sql',
      redirect: { name: 'blob-browse', query: { mode: 'sql' } },
    },
  )
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
