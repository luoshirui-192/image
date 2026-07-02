<script setup>

import { onMounted, reactive, ref } from 'vue'

import { useRoute, useRouter } from 'vue-router'

import { ElMessage } from 'element-plus'

import { Lock, User } from '@element-plus/icons-vue'

import { APP_NAME } from '@/config/app'

import { REMEMBER_USERNAME_KEY } from '@/config/app'

import { useAuthStore } from '@/stores/auth'



const router = useRouter()

const route = useRoute()

const auth = useAuthStore()



const loading = ref(false)

const formRef = ref()

const remember = ref(localStorage.getItem(REMEMBER_USERNAME_KEY) !== null)



const form = reactive({

  username: localStorage.getItem(REMEMBER_USERNAME_KEY) || 'admin',

  password: '',

})



const rules = {

  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],

  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],

}



onMounted(() => {

  if (auth.isAuthenticated) {

    router.replace('/')

  }

})



async function onSubmit() {

  await formRef.value.validate()

  loading.value = true

  try {

    await auth.login(form.username, form.password)

    if (remember.value) {

      localStorage.setItem(REMEMBER_USERNAME_KEY, form.username)

    } else {

      localStorage.removeItem(REMEMBER_USERNAME_KEY)

    }

    ElMessage.success('登录成功')

    const redirect = route.query.redirect || '/'

    router.replace(String(redirect))

  } catch (err) {

    ElMessage.error(err.message || '登录失败')

  } finally {

    loading.value = false

  }

}

</script>



<template>

  <div class="login-page">

    <div class="login-panel">

      <div class="login-intro">

        <h1>{{ APP_NAME }}</h1>

        <p>图片元数据 + 路径存储 + SQL 自定义查询面板</p>

        <ul>

          <li>上传图片自动分层存储并写入数据库路径</li>

          <li>管理员可执行只读 SELECT 查询并预览结果</li>

          <li>支持分类、标签、操作日志与权限控制</li>

        </ul>

      </div>



      <el-card class="login-card" shadow="hover">

        <h2>用户登录</h2>

        <p class="hint">默认管理员：admin / admin123</p>



        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="onSubmit">

          <el-form-item label="用户名" prop="username">

            <el-input

              v-model="form.username"

              placeholder="请输入用户名"

              :prefix-icon="User"

              autocomplete="username"

            />

          </el-form-item>

          <el-form-item label="密码" prop="password">

            <el-input

              v-model="form.password"

              type="password"

              show-password

              placeholder="请输入密码"

              :prefix-icon="Lock"

              autocomplete="current-password"

              @keyup.enter="onSubmit"

            />

          </el-form-item>

          <div class="form-extra">

            <el-checkbox v-model="remember">记住用户名</el-checkbox>

          </div>

          <el-button type="primary" class="submit-btn" :loading="loading" native-type="submit" @click="onSubmit">

            登录

          </el-button>

        </el-form>

      </el-card>

    </div>

  </div>

</template>



<style scoped>

.login-page {

  min-height: 100vh;

  display: flex;

  align-items: center;

  justify-content: center;

  background: linear-gradient(135deg, #1d2b3a 0%, #2c5364 50%, #203a43 100%);

  padding: 24px;

}



.login-panel {

  display: grid;

  grid-template-columns: 1fr minmax(320px, 400px);

  gap: 48px;

  max-width: 960px;

  width: 100%;

  align-items: center;

}



.login-intro {

  color: #fff;

}



.login-intro h1 {

  margin: 0 0 12px;

  font-size: 26px;

  line-height: 1.3;

}



.login-intro p {

  margin: 0 0 20px;

  color: rgba(255, 255, 255, 0.85);

  line-height: 1.6;

}



.login-intro ul {

  margin: 0;

  padding-left: 18px;

  color: rgba(255, 255, 255, 0.75);

  line-height: 1.8;

}



.login-card {

  border-radius: 12px;

}



.login-card h2 {

  margin: 0 0 8px;

  font-size: 22px;

}



.hint {

  margin: 0 0 20px;

  color: #909399;

  font-size: 13px;

}



.form-extra {

  margin-bottom: 4px;

}



.submit-btn {

  width: 100%;

  margin-top: 8px;

}



@media (max-width: 768px) {

  .login-panel {

    grid-template-columns: 1fr;

    gap: 24px;

  }



  .login-intro {

    text-align: center;

  }



  .login-intro ul {

    text-align: left;

  }

}

</style>


