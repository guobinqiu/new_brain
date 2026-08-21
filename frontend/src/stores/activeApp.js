import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const ACTIVE_APP_KEY = 'rag_active_app_id'

export const useActiveAppStore = defineStore('activeApp', () => {
  const appId = ref(localStorage.getItem(ACTIVE_APP_KEY) || '')
  const databaseStatus = ref(null)

  watch(appId, value => {
    if (value) localStorage.setItem(ACTIVE_APP_KEY, value)
    else localStorage.removeItem(ACTIVE_APP_KEY)
  })

  return { appId, databaseStatus }
})
