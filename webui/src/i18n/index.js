import { createI18n } from 'vue-i18n'
import zh from './locales/zh.json'
import en from './locales/en.json'

const savedLocale = localStorage.getItem('rag_lang')

export const i18n = createI18n({
  legacy: false,
  locale: savedLocale || 'zh',
  fallbackLocale: 'zh',
  messages: { zh, en },
})
