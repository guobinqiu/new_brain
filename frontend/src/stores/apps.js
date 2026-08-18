import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from '../utils/api'
import { useDatabaseStore } from './database'

export const useAppsStore = defineStore('apps', () => {
  const apps = ref([])

  async function fetchApps() {
    try {
      const res = await axios.get('/api/admin/apps')
      apps.value = res.data.apps || []
      const databaseStore = useDatabaseStore()
      if (databaseStore.databaseAppId && !apps.value.some(app => app.app_id === databaseStore.databaseAppId)) {
        databaseStore.databaseAppId = ''
        databaseStore.databaseStatus = null
      }
    } catch (err) { console.error(err) }
  }

  return { apps, fetchApps }
})
