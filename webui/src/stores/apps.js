import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from '../utils/api'
import { errorMessage, showToast } from '../utils/toast'
import { useActiveAppStore } from './activeApp'

export const useAppsStore = defineStore('apps', () => {
  const apps = ref([])

  async function fetchApps() {
    try {
      const res = await axios.get('/api/rag/apps')
      apps.value = res.data.apps || []
      const activeAppStore = useActiveAppStore()
      if (activeAppStore.appId && !apps.value.some(app => app.app_id === activeAppStore.appId)) {
        activeAppStore.appId = ''
        activeAppStore.databaseStatus = null
      }
    } catch (err) { showToast('error', errorMessage(err)) }
  }

  async function createApp(appId) {
    const res = await axios.post('/api/rag/apps', { app_id: appId })
    await fetchApps()
    return res.data
  }

  async function deleteApp(appId) {
    const res = await axios.delete(`/api/rag/apps/${appId}`)
    await fetchApps()
    return res.data
  }

  return { apps, fetchApps, createApp, deleteApp }
})
