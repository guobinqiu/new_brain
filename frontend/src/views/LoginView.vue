<template>
  <main class="login-view">
    <el-form class="login-card" label-position="top" @submit.prevent="login">
      <div>
        <h2>{{ t('auth.title') }}</h2>
        <p>{{ t('auth.desc') }}</p>
      </div>
      <el-form-item :label="t('auth.username')">
        <el-input v-model.trim="loginForm.username" autocomplete="username" />
      </el-form-item>
      <el-form-item :label="t('auth.password')">
        <el-input v-model="loginForm.password" type="password" show-password autocomplete="current-password" />
      </el-form-item>
      <el-button type="primary" class="login-submit" native-type="submit">{{ t('auth.login') }}</el-button>
      <div v-if="loginError" class="upload-feedback error">{{ loginError }}</div>
    </el-form>
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'
import { useAuthStore } from '../stores/auth'

const API = '/api'
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const loginForm = ref({ username: 'admin', password: '' })
const loginError = ref('')

async function login() {
  loginError.value = ''
  try {
    const res = await axios.post(`${API}/login`, {
      username: loginForm.value.username,
      password: loginForm.value.password,
    })
    authStore.setToken(res.data.access_token)
    router.push('/apps')
  } catch (err) {
    loginError.value = err.response?.data?.detail || err.message
  }
}
</script>
