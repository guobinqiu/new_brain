import axios from 'axios'
import { useAuthStore } from '../stores/auth'
import { stopLogStream } from './logStream'
import router from '../router'

axios.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      stopLogStream()
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
