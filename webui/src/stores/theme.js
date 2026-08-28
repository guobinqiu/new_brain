import { defineStore } from 'pinia'
import { ref } from 'vue'

function applyTheme(value) {
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('dark', value === 'dark')
  }
}

export const useThemeStore = defineStore('theme', () => {
  const theme = ref(localStorage.getItem('rag_theme') || 'light')
  applyTheme(theme.value)

  function setTheme(value) {
    theme.value = value
    localStorage.setItem('rag_theme', value)
    applyTheme(value)
  }

  return { theme, setTheme }
})
