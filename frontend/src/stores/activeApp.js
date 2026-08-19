import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useActiveAppStore = defineStore('activeApp', () => {
  const appId = ref('')
  const databaseStatus = ref(null)

  return { appId, databaseStatus }
})
