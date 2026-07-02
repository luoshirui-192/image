<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Document, FolderOpened, PictureFilled, UploadFilled } from '@element-plus/icons-vue'
import { healthApi } from '@/api/auth'
import { APP_VERSION } from '@/config/app'
import { filterMenuByRole } from '@/config/menu'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const health = ref(null)
const loading = ref(true)

const quickMenus = computed(() =>
  filterMenuByRole(auth.isAdmin).filter((item) => item.name !== 'home').slice(0, 4),
)

const iconMap = { UploadFilled, FolderOpened, Document, PictureFilled }

const roleLabel = computed(() => (auth.isAdmin ? '服务器管理员' : '客户端用户'))

const roleHint = computed(() =>
  auth.isAdmin
    ? '可管理数据库、SQL 查询、批量导入与全部图片'
    : '可上传图片到服务器、浏览/下载图片，无法访问数据库',
)

function goToMenu(item) {
  router.push(item.path ? `/${item.path}` : '/')
}

onMounted(async () => {
  try {
    const res = await healthApi()
    health.value = res.data
  } catch {
    health.value = null
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <div class="page-card welcome-header">
      <h2 class="page-title">欢迎回来，{{ auth.username }}</h2>
      <p class="desc">
        <template v-if="auth.isAdmin">
          图像路径式数据库管理系统 — 服务器端：原文件存储、路径入库、SQL 查询与运维管理。
        </template>
        <template v-else>
          图像库客户端 — 上传图片到服务器、浏览与下载原文件；数据库仅服务器管理员可访问。
        </template>
      </p>
    </div>

    <el-row :gutter="16" class="stat-row">
      <el-col :xs="24" :sm="12" :md="8">
        <el-card shadow="never" class="stat-card">
          <template #header>当前用户</template>
          <p><strong>用户名：</strong>{{ auth.username }}</p>
          <p><strong>角色：</strong>{{ roleLabel }}</p>
          <p><strong>权限：</strong>{{ roleHint }}</p>
        </el-card>
      </el-col>

      <el-col :xs="24" :sm="12" :md="8">
        <el-card shadow="never" class="stat-card" v-loading="loading">
          <template #header>服务状态</template>
          <template v-if="health">
            <p><strong>服务：</strong>{{ health.service }}</p>
            <p><strong>数据库：</strong>{{ auth.isAdmin ? health.db_engine : '（客户端不可见）' }}</p>
            <p><strong>版本：</strong>{{ health.version }}</p>
          </template>
          <el-alert
            v-else
            title="无法连接服务器，请确认服务已启动"
            type="warning"
            show-icon
            :closable="false"
          />
        </el-card>
      </el-col>

      <el-col :xs="24" :sm="12" :md="8">
        <el-card shadow="never" class="stat-card">
          <template #header>使用说明</template>
          <template v-if="auth.isAdmin">
            <p>图片原文件保存在服务器 <code>upload/</code> 目录，路径记录在 MySQL。</p>
            <p>可在本机使用 Navicat 连接 <code>127.0.0.1:3306</code> 管理数据库。</p>
          </template>
          <template v-else>
            <p>上传的图片保存在<strong>服务器</strong>，不会留在您的电脑里。</p>
            <p>在「图片列表」可预览、下载原文件；默认显示您上传的图片。</p>
          </template>
        </el-card>
      </el-col>
    </el-row>

    <div class="page-card quick-nav">
      <h3 class="section-title">快捷导航</h3>
      <el-row :gutter="12">
        <el-col v-for="item in quickMenus" :key="item.name" :xs="12" :sm="6">
          <div class="nav-card" @click="goToMenu(item)">
            <el-icon :size="28" color="#409eff">
              <component :is="iconMap[item.icon] || Document" />
            </el-icon>
            <div class="nav-title">{{ item.title }}</div>
            <div class="nav-desc">{{ item.description }}</div>
          </div>
        </el-col>
      </el-row>
    </div>

    <p class="version-hint">前端 v{{ APP_VERSION }} · 图像路径式数据库管理系统</p>
  </div>
</template>

<style scoped>
.welcome-header {
  margin-bottom: 16px;
}

.desc {
  color: #606266;
  margin: 0;
  line-height: 1.6;
}

.stat-row {
  margin-bottom: 16px;
}

.stat-card p {
  margin: 6px 0;
  color: #606266;
  font-size: 14px;
  line-height: 1.6;
}

.stat-card code {
  background: #f5f7fa;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 13px;
}

.quick-nav {
  margin-bottom: 12px;
}

.section-title {
  margin: 0 0 16px;
  font-size: 16px;
  font-weight: 600;
}

.nav-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
  margin-bottom: 12px;
  min-height: 110px;
}

.nav-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
}

.nav-title {
  font-weight: 600;
  margin: 8px 0 4px;
  color: #303133;
}

.nav-desc {
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}

.version-hint {
  text-align: center;
  font-size: 12px;
  color: #909399;
  margin: 8px 0 0;
}
</style>
