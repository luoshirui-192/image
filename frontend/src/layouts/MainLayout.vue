<script setup>

import { computed, onMounted, onUnmounted, ref } from 'vue'

import { useRoute, useRouter } from 'vue-router'

import { ElMessageBox } from 'element-plus'

import {

  Document,

  Expand,

  Fold,

  FolderOpened,

  HomeFilled,

  List,

  Menu as MenuIcon,

  PictureFilled,

  Setting,

  UploadFilled,

} from '@element-plus/icons-vue'

import AppBreadcrumb from '@/components/AppBreadcrumb.vue'

import {

  APP_SHORT_NAME,

  APP_TAGLINE,

  APP_VERSION,

} from '@/config/app'

import { filterMenuByRole, resolveActiveMenuPath } from '@/config/menu'

import { useAuthStore } from '@/stores/auth'



const SIDEBAR_COLLAPSED_KEY = 'image_db_sidebar_collapsed'



const route = useRoute()

const router = useRouter()

const auth = useAuthStore()



const collapsed = ref(localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1')

const mobileOpen = ref(false)

const isMobile = ref(false)



const iconMap = {

  HomeFilled,

  UploadFilled,

  FolderOpened,

  Document,

  PictureFilled,

  Menu: MenuIcon,

  List,

  Setting,

}



const menuItems = computed(() => filterMenuByRole(auth.isAdmin))



const activeMenu = computed(() => resolveActiveMenuPath(route.path))



const asideWidth = computed(() => (collapsed.value ? 'var(--sidebar-collapsed-width)' : 'var(--sidebar-width)'))



function toggleCollapse() {

  collapsed.value = !collapsed.value

  localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed.value ? '1' : '0')

}



function openMobileMenu() {

  mobileOpen.value = true

}



function closeMobileMenu() {

  mobileOpen.value = false

}



function onMenuSelect() {

  if (isMobile.value) {

    closeMobileMenu()

  }

}



function checkMobile() {

  isMobile.value = window.innerWidth < 992

  if (!isMobile.value) {

    mobileOpen.value = false

  }

}



async function handleLogout() {

  await ElMessageBox.confirm('确定退出登录吗？', '提示', { type: 'warning' })

  auth.logout()

  router.push({ name: 'login' })

}



function handleUserCommand(command) {

  if (command === 'logout') {

    handleLogout()

  } else if (command === 'home') {

    router.push({ name: 'home' })

  }

}



onMounted(() => {

  checkMobile()

  window.addEventListener('resize', checkMobile)

})



onUnmounted(() => {

  window.removeEventListener('resize', checkMobile)

})

</script>



<template>

  <el-container class="layout-root">

    <!-- Desktop sidebar -->

    <el-aside v-if="!isMobile" :width="asideWidth" class="layout-aside" :class="{ 'is-collapsed': collapsed }">

      <div class="brand">

        <span class="brand-icon">图</span>

        <div v-show="!collapsed" class="brand-text">

          <div class="brand-title">{{ APP_SHORT_NAME }}</div>

          <div class="brand-sub">{{ APP_TAGLINE }}</div>

        </div>

      </div>



      <el-scrollbar class="menu-scroll">

        <el-menu

          :default-active="activeMenu"

          :collapse="collapsed"

          :collapse-transition="false"

          router

          background-color="var(--sidebar-bg)"

          text-color="#c0c4cc"

          active-text-color="#ffffff"

          class="side-menu"

          @select="onMenuSelect"

        >

          <el-menu-item

            v-for="item in menuItems"

            :key="item.name"

            :index="item.path ? `/${item.path}` : '/'"

          >

            <el-icon><component :is="iconMap[item.icon]" /></el-icon>

            <template #title>

              <span>{{ item.title }}</span>

              <el-tag v-if="item.adminOnly && !collapsed" size="small" type="danger" class="admin-tag">

                管理

              </el-tag>

            </template>

          </el-menu-item>

        </el-menu>

      </el-scrollbar>



      <div class="aside-footer" v-show="!collapsed">

        <span>v{{ APP_VERSION }}</span>

      </div>

    </el-aside>



    <!-- Mobile drawer -->

    <el-drawer

      v-model="mobileOpen"

      direction="ltr"

      size="260px"

      :with-header="false"

      class="mobile-drawer"

    >

      <div class="drawer-brand">

        <span class="brand-icon">图</span>

        <div>

          <div class="brand-title">{{ APP_SHORT_NAME }}</div>

          <div class="brand-sub">{{ APP_TAGLINE }}</div>

        </div>

      </div>

      <el-menu

        :default-active="activeMenu"

        router

        background-color="var(--sidebar-bg)"

        text-color="#c0c4cc"

        active-text-color="#ffffff"

        class="side-menu mobile-menu"

        @select="onMenuSelect"

      >

        <el-menu-item

          v-for="item in menuItems"

          :key="item.name"

          :index="item.path ? `/${item.path}` : '/'"

        >

          <el-icon><component :is="iconMap[item.icon]" /></el-icon>

          <span>{{ item.title }}</span>

        </el-menu-item>

      </el-menu>

    </el-drawer>



    <el-container class="layout-main-wrap">

      <el-header class="layout-header">

        <div class="header-left">

          <el-button

            v-if="isMobile"

            :icon="MenuIcon"

            circle

            text

            class="menu-trigger"

            @click="openMobileMenu"

          />

          <el-button

            v-else

            :icon="collapsed ? Expand : Fold"

            circle

            text

            class="menu-trigger"

            @click="toggleCollapse"

          />

          <AppBreadcrumb />

        </div>



        <div class="header-right">

          <el-tag size="small" :type="auth.isAdmin ? 'danger' : 'info'" effect="plain">

            {{ auth.isAdmin ? '管理员' : '普通用户' }}

          </el-tag>

          <el-dropdown trigger="click" @command="handleUserCommand">

            <span class="user-trigger">

              <el-avatar :size="28" class="user-avatar">{{ auth.username.charAt(0).toUpperCase() }}</el-avatar>

              <span class="username">{{ auth.username }}</span>

            </span>

            <template #dropdown>

              <el-dropdown-menu>

                <el-dropdown-item command="home">返回首页</el-dropdown-item>

                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>

              </el-dropdown-menu>

            </template>

          </el-dropdown>

        </div>

      </el-header>



      <el-main class="layout-main">

        <router-view v-slot="{ Component }">

          <transition name="fade-slide" mode="out-in">

            <component :is="Component" />

          </transition>

        </router-view>

      </el-main>



      <el-footer class="layout-footer" height="36px">

        <span>{{ APP_SHORT_NAME }}</span>

      </el-footer>

    </el-container>

  </el-container>

</template>



<style scoped>

.layout-root {

  min-height: 100vh;

}



.layout-aside {

  background: var(--sidebar-bg);

  color: #fff;

  display: flex;

  flex-direction: column;

  transition: width 0.2s ease;

  overflow: hidden;

}



.brand,

.drawer-brand {

  display: flex;

  align-items: center;

  gap: 12px;

  padding: 16px;

  border-bottom: 1px solid rgba(255, 255, 255, 0.08);

  flex-shrink: 0;

}



.drawer-brand {

  background: var(--sidebar-bg);

  color: #fff;

}



.brand-icon {

  width: 36px;

  height: 36px;

  border-radius: 8px;

  background: linear-gradient(135deg, #409eff, #67c23a);

  display: inline-flex;

  align-items: center;

  justify-content: center;

  font-weight: 700;

  flex-shrink: 0;

}



.brand-title {

  font-size: 14px;

  font-weight: 600;

  white-space: nowrap;

}



.brand-sub {

  font-size: 11px;

  color: #909399;

  margin-top: 2px;

  white-space: nowrap;

}



.menu-scroll {

  flex: 1;

}



.side-menu {

  border-right: none;

}



.side-menu:not(.el-menu--collapse) {

  width: var(--sidebar-width);

}



.admin-tag {

  margin-left: 8px;

  transform: scale(0.85);

}



.aside-footer {

  padding: 12px 16px;

  font-size: 11px;

  color: #909399;

  border-top: 1px solid rgba(255, 255, 255, 0.08);

}



.layout-main-wrap {

  min-width: 0;

}



.layout-header {

  height: var(--header-height);

  background: #fff;

  border-bottom: 1px solid #ebeef5;

  display: flex;

  align-items: center;

  justify-content: space-between;

  padding: 0 16px;

  gap: 12px;

}



.header-left {

  display: flex;

  align-items: center;

  gap: 8px;

  min-width: 0;

  flex: 1;

}



.menu-trigger {

  flex-shrink: 0;

}



.header-right {

  display: flex;

  align-items: center;

  gap: 12px;

  flex-shrink: 0;

}



.user-trigger {

  display: inline-flex;

  align-items: center;

  gap: 8px;

  cursor: pointer;

  outline: none;

}



.user-avatar {

  background: #409eff;

  color: #fff;

  font-size: 13px;

}



.username {

  color: #606266;

  font-size: 14px;

  max-width: 120px;

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

}



.layout-main {

  padding: 16px 20px 20px;

  background: var(--app-bg);

  min-height: calc(100vh - var(--header-height) - 36px);

}



.layout-footer {

  display: flex;

  align-items: center;

  justify-content: center;

  font-size: 12px;

  color: #909399;

  background: #fff;

  border-top: 1px solid #ebeef5;

}



.fade-slide-enter-active,

.fade-slide-leave-active {

  transition: opacity 0.15s ease, transform 0.15s ease;

}



.fade-slide-enter-from {

  opacity: 0;

  transform: translateY(6px);

}



.fade-slide-leave-to {

  opacity: 0;

  transform: translateY(-4px);

}



@media (max-width: 991px) {

  .username {

    display: none;

  }

}

</style>



<style>

.mobile-drawer .el-drawer__body {

  padding: 0;

  background: var(--sidebar-bg);

}



.mobile-drawer .mobile-menu {

  border-right: none;

}

</style>


