<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { HomeFilled } from '@element-plus/icons-vue'
import { APP_NAME } from '@/config/app'
import { findMenuItemByPath } from '@/config/menu'

const route = useRoute()

const breadcrumbs = computed(() => {
  const items = [{ title: APP_NAME, path: '/' }]
  const current = findMenuItemByPath(route.path)

  if (current && current.name !== 'home') {
    items.push({ title: current.title, path: current.path ? `/${current.path}` : '/' })
  } else if (route.meta?.title && route.name !== 'home') {
    if (route.query.from) {
      const fromPath = String(route.query.from).replace(/^\//, '')
      const parent = findMenuItemByPath(fromPath)
      if (parent) {
        items.push({ title: parent.title, path: parent.path ? `/${parent.path}` : '/' })
      }
    }
    items.push({ title: route.meta.title, path: route.path })
  } else if (route.name === 'home' || route.path === '/') {
    items.push({ title: '首页', path: '/' })
  }

  return items
})
</script>

<template>
  <el-breadcrumb separator="/" class="app-breadcrumb">
    <el-breadcrumb-item
      v-for="(item, index) in breadcrumbs"
      :key="item.path + index"
      :to="index < breadcrumbs.length - 1 ? item.path : undefined"
    >
      <el-icon v-if="index === 0" class="home-icon"><HomeFilled /></el-icon>
      {{ item.title }}
    </el-breadcrumb-item>
  </el-breadcrumb>
</template>

<style scoped>
.app-breadcrumb {
  font-size: 14px;
}

.home-icon {
  margin-right: 4px;
  vertical-align: -2px;
}
</style>
