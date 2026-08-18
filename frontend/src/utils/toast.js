import { ElMessage } from 'element-plus'

export function showToast(type, text) {
  ElMessage({
    type,
    message: text,
    duration: type === 'error' ? 5200 : 3200,
  })
}
