import axios from 'axios'
import { useAuthStore } from '../stores/auth'
import router from '../router'
import { stopLogsTail } from './loki'

axios.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      stopLogsTail()
      try {
        useAuthStore().clearAuth()
      } catch (e) {
        localStorage.removeItem('rag_token')
        delete axios.defaults.headers.common.Authorization
      }
      router.replace('/login')
    }
    return Promise.reject(error)
  },
)

export default axios
