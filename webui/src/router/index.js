import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import AppsView from '../views/AppsView.vue'
import DatabaseView from '../views/DatabaseView.vue'
import UploadView from '../views/UploadView.vue'
import SearchView from '../views/SearchView.vue'
import LlmView from '../views/LlmView.vue'
import DebugView from '../views/DebugView.vue'
import TracesView from '../views/TracesView.vue'
// import LogsView from '../views/LogsView.vue'
import OpsView from '../views/OpsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/apps', component: AppsView },
    { path: '/apps/:app_id/database', component: DatabaseView },
    { path: '/apps/:app_id/upload', component: UploadView },
    { path: '/apps/:app_id/search', component: SearchView },
    { path: '/apps/:app_id/llm', redirect: '/llm' },
    { path: '/apps/:app_id/debug', redirect: '/debug' },
    { path: '/apps/:app_id/trace', component: TracesView },
    { path: '/database', component: DatabaseView },
    { path: '/upload', component: UploadView },
    { path: '/search', component: SearchView },
    { path: '/llm', component: LlmView },
    { path: '/debug', component: DebugView },
    { path: '/trace', component: TracesView },
    // { path: '/logs', component: LogsView },
    { path: '/config', redirect: '/ops' },
    { path: '/ops', component: OpsView },
    { path: '/', redirect: '/apps' },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('rag_token')
  if (!token && !to.meta.public) return { path: '/login' }
  if (token && to.path === '/login') return { path: '/apps' }
})

export default router
