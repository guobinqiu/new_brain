import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'

export const useAuthStore = defineStore('auth', () => {
  const authToken = ref(localStorage.getItem('rag_token') || '')

  function setToken(token) {
    authToken.value = token
    localStorage.setItem('rag_token', token)
    applyAuthHeader()
  }

  function applyAuthHeader() {
    if (authToken.value) axios.defaults.headers.common.Authorization = `Bearer ${authToken.value}`
  }

  function clearAuth() {
    authToken.value = ''
    localStorage.removeItem('rag_token')
    delete axios.defaults.headers.common.Authorization
  }

  if (authToken.value) applyAuthHeader()

  return { authToken, setToken, applyAuthHeader, clearAuth }
})
