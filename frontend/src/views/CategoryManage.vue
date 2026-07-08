<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Plus } from '@element-plus/icons-vue'
import {
  createCategoryApi,
  deleteCategoryApi,
  formatDateTime,
  listCategoriesApi,
  updateCategoryApi,
} from '@/api/images'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const categories = ref([])

const dialogVisible = ref(false)
const dialogSaving = ref(false)
const isEdit = ref(false)

const form = reactive({
  id: null,
  category_name: '',
  sort: 0,
})

const backTarget = computed(() => {
  const from = String(route.query.from || '').replace(/^\//, '')
  if (from === 'upload') {
    return { path: '/upload', label: '返回上传' }
  }
  if (from === 'blob-migrate') {
    return { path: '/blob-migrate', label: '返回迁移' }
  }
  return { path: '/', label: '返回首页' }
})

async function loadCategories() {
  loading.value = true
  try {
    const res = await listCategoriesApi()
    categories.value = res.data || []
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.id = null
  form.category_name = ''
  form.sort = 0
}

function openCreate() {
  resetForm()
  isEdit.value = false
  dialogVisible.value = true
}

function openEdit(row) {
  form.id = row.id
  form.category_name = row.category_name
  form.sort = row.sort ?? 0
  isEdit.value = true
  dialogVisible.value = true
}

async function submitForm() {
  const name = form.category_name.trim()
  if (!name) {
    ElMessage.warning('分类名称不能为空')
    return
  }

  dialogSaving.value = true
  try {
    if (isEdit.value) {
      await updateCategoryApi(form.id, {
        category_name: name,
        sort: Number(form.sort) || 0,
      })
      ElMessage.success('分类已更新')
    } else {
      await createCategoryApi({
        category_name: name,
        sort: Number(form.sort) || 0,
      })
      ElMessage.success('分类已创建')
    }
    dialogVisible.value = false
    loadCategories()
  } finally {
    dialogSaving.value = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除分类「${row.category_name}」吗？若分类下仍有图片将无法删除。`,
      '确认删除',
      { type: 'warning' },
    )
    await deleteCategoryApi(row.id)
    ElMessage.success('分类已删除')
    loadCategories()
  } catch (err) {
    if (err !== 'cancel' && err?.message) {
      // interceptor shows error
    }
  }
}

function goBack() {
  router.push(backTarget.value.path)
}

onMounted(loadCategories)
</script>

<template>
  <div class="category-page">
    <div class="page-card">
      <div class="header-row">
        <div>
          <el-button link type="primary" class="back-btn" @click="goBack">
            <el-icon><ArrowLeft /></el-icon>
            {{ backTarget.label }}
          </el-button>
          <h2 class="page-title">分类管理</h2>
          <p class="page-desc">
            维护上传与迁移使用的图片分类。上传、迁移页可直接新建；此处可改名、排序或删除空分类。
          </p>
        </div>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增分类</el-button>
      </div>

      <el-table v-loading="loading" :data="categories" stripe border style="width: 100%">
        <el-table-column prop="id" label="ID" width="80" align="center" />
        <el-table-column prop="category_name" label="分类名称" min-width="160" />
        <el-table-column prop="sort" label="排序" width="100" align="center" />
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.create_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑分类' : '新增分类'"
      width="420px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="form.category_name" maxlength="100" placeholder="如：风景、人物" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort" :min="0" :max="9999" />
          <span class="field-hint">数值越小越靠前</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dialogSaving" @click="submitForm">保存</el-button>
      </template>
    </dialog>
  </div>
</template>

<style scoped>
.header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.back-btn {
  padding-left: 0;
  margin-bottom: 4px;
}

.page-desc {
  margin: 4px 0 0;
  color: #606266;
  line-height: 1.6;
  font-size: 14px;
}

.field-hint {
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}
</style>
