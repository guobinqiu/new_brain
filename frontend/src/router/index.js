import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import AppsView from '../views/AppsView.vue'
import DatabaseView from '../views/DatabaseView.vue'
import UploadView from '../views/UploadView.vue'
import SearchView from '../views/SearchView.vue'
import MonitorView from '../views/MonitorView.vue'
import TracesView from '../views/TracesView.vue'
import LogsView from '../views/LogsView.vue'
import ConfigView from '../views/ConfigView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/apps', component: AppsView },
    { path: '/database', component: DatabaseView },
    { path: '/upload', component: UploadView },
    { path: '/search', component: SearchView },
    { path: '/monitor', component: MonitorView },
    { path: '/trace', component: TracesView },
    { path: '/logs', component: LogsView },
    { path: '/config', component: ConfigView },
    { path: '/', redirect: '/apps' },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('rag_token')
  if (!token && !to.meta.public) return { path: '/login' }
  if (token && to.path === '/login') return { path: '/apps' }
})

export default router
