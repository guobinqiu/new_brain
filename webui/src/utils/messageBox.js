import { ElMessageBox } from 'element-plus'

export function confirmBox(t, message, title, options = {}) {
  return ElMessageBox.confirm(message, title, {
    confirmButtonText: t('common.confirm'),
    cancelButtonText: t('common.cancel'),
    ...options,
  })
}
