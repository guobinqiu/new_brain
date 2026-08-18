import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import App from './App.vue'
import { i18n } from './i18n'
import router from './router'
import { createPinia } from 'pinia'
import './utils/api'

// Element Plus 语言随 vue-i18n locale 切换
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
const epLocale = {
  zh: zhCn,
  en,
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(ElementPlus, { locale: epLocale[i18n.global.locale.value] })
app.mount('#app')
