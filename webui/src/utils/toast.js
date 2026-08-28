import { ElMessage } from 'element-plus'

export function showToast(type, text) {
  ElMessage({
    type,
    message: text,
    duration: type === 'error' ? 5200 : 3200,
  })
}

export function errorMessage(error, fallback = 'Request failed') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) return detail.map(item => item?.msg || String(item)).join('; ')
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  if (typeof error?.response?.data === 'string' && error.response.data) return error.response.data
  return error?.message || fallback
}
