import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useDatabaseStore = defineStore('database', () => {
  const databaseAppId = ref('')
  const databaseStatus = ref(null)

  return { databaseAppId, databaseStatus }
})
