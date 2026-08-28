import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from '../utils/api'
import { useActiveAppStore } from './activeApp'

export const useAppsStore = defineStore('apps', () => {
  const apps = ref([])

  async function fetchApps() {
    try {
      const res = await axios.get('/api/apps')
      apps.value = res.data.apps || []
      const activeAppStore = useActiveAppStore()
      if (activeAppStore.appId && !apps.value.some(app => app.app_id === activeAppStore.appId)) {
        activeAppStore.appId = ''
        activeAppStore.databaseStatus = null
      }
    } catch (err) { console.error(err) }
  }

  return { apps, fetchApps }
})
