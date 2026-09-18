<template>
  <el-config-provider :locale="epLocale">
  <div class="app">
    <div v-if="!authToken" class="login-tools">
      <div class="switch-group">
        <el-radio-group :model-value="lang" size="small" @update:model-value="setLang">
          <el-radio-button value="zh">中</el-radio-button>
          <el-radio-button value="en">EN</el-radio-button>
        </el-radio-group>
      </div>
      <div class="switch-group">
        <el-radio-group :model-value="theme" size="small" @update:model-value="setTheme">
          <el-radio-button value="light">{{ t('theme.light') }}</el-radio-button>
          <el-radio-button value="dark">{{ t('theme.dark') }}</el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <router-view v-if="!authToken" />

    <template v-if="authToken">
      <header class="app-header">
        <div class="header-top">
          <div>
            <h1>{{ t('app.title') }}</h1>
            <p class="header-desc">{{ t('app.desc') }}</p>
          </div>
          <div class="header-actions">
            <div class="switch-group">
              <el-radio-group :model-value="lang" size="small" @update:model-value="setLang">
                <el-radio-button value="zh">中</el-radio-button>
                <el-radio-button value="en">EN</el-radio-button>
              </el-radio-group>
            </div>
            <div class="switch-group">
              <el-radio-group :model-value="theme" size="small" @update:model-value="setTheme">
                <el-radio-button value="light">{{ t('theme.light') }}</el-radio-button>
                <el-radio-button value="dark">{{ t('theme.dark') }}</el-radio-button>
              </el-radio-group>
            </div>
            <el-button size="small" @click="logout">{{ t('auth.logout') }}</el-button>
          </div>
        </div>
      </header>

      <div class="console-shell">
        <aside class="side-menu">
          <el-menu
            :default-active="activeMenu"
            class="side-nav"
            @select="onMenuSelect"
          >
            <el-menu-item index="/apps">{{ t('nav.apps') }}</el-menu-item>
            <el-sub-menu v-for="app in apps" :key="app.app_id" :index="`app-${app.app_id}`">
              <template #title>
                <span @click.stop="selectApp(app.app_id)">{{ app.app_id }}</span>
              </template>
              <el-menu-item :index="`/apps/${app.app_id}/database`">{{ t('nav.database') }}</el-menu-item>
              <el-menu-item :index="`/apps/${app.app_id}/upload`">{{ t('nav.upload') }}</el-menu-item>
              <el-menu-item :index="`/apps/${app.app_id}/search`">{{ t('nav.search') }}</el-menu-item>
              <el-menu-item :index="`/apps/${app.app_id}/trace`">{{ t('nav.trace') }}</el-menu-item>
            </el-sub-menu>
            <el-menu-item index="/llm">{{ t('nav.llm') }}</el-menu-item>
            <el-menu-item index="/debug">{{ t('nav.debug') }}</el-menu-item>
            <el-menu-item index="/logs">{{ t('nav.logs') }}</el-menu-item>
            <el-menu-item index="/ops">{{ t('nav.ops') }}</el-menu-item>
          </el-menu>
        </aside>

        <section class="console-main">
          <div v-if="showAppContext" class="app-context">
            <span>{{ t('apps.current') }}</span>
            <strong>{{ appId }}</strong>
          </div>

          <router-view :key="routerViewKey" />
        </section>
      </div>
    </template>
  </div>
  </el-config-provider>
</template>

<script setup>
import { computed, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import { useAuthStore } from './stores/auth'
import { useThemeStore } from './stores/theme'
import { useActiveAppStore } from './stores/activeApp'
import { useAppsStore } from './stores/apps'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()

const authStore = useAuthStore()
const { authToken } = storeToRefs(authStore)

const themeStore = useThemeStore()
const { theme } = storeToRefs(themeStore)

const activeAppStore = useActiveAppStore()
const { appId } = storeToRefs(activeAppStore)

const appsStore = useAppsStore()
const { apps } = storeToRefs(appsStore)

const lang = computed(() => locale.value)
const epLocale = computed(() => (locale.value === 'zh' ? zhCn : en))

const SUB_PAGES = ['database', 'upload', 'search', 'llm', 'debug', 'trace']

const routerViewKey = computed(() => (appId.value ? `${appId.value}${route.path}` : route.path))
const routeAppPage = computed(() => route.path.split('/')[3] || '')
const showAppContext = computed(() => Boolean(route.params.app_id))

const activeMenu = computed(() => {
  if (route.params.app_id && SUB_PAGES.includes(routeAppPage.value)) {
    return `/apps/${route.params.app_id}/${routeAppPage.value}`
  }
  return route.path
})

function onMenuSelect(index) {
  if (index === '/apps' || index === '/llm' || index === '/debug' || index === '/logs' || index === '/ops') {
    router.push(index)
    return
  }
  const parts = index.split('/')          // ['', 'apps', appId, page]
  if (parts.length === 4 && parts[1] === 'apps') {
    if (activeAppStore.appId !== parts[2]) {
      activeAppStore.appId = parts[2]
      activeAppStore.databaseStatus = null
    }
    router.push(index)
  }
}

function selectApp(appId) {
  if (activeAppStore.appId !== appId) {
    activeAppStore.appId = appId
    activeAppStore.databaseStatus = null
  }
  router.push(`/apps/${appId}/database`)
}

function setLang(value) {
  locale.value = value
  localStorage.setItem('rag_lang', value)
}

function setTheme(value) {
  themeStore.setTheme(value)
}

function logout() {
  activeAppStore.appId = ''
  activeAppStore.databaseStatus = null
  authStore.clearAuth()
  router.push('/login')
}

onMounted(() => {
  if (authToken.value) appsStore.fetchApps()
})

watch(authToken, value => {
  if (value) appsStore.fetchApps()
})

watch(() => route.params.app_id, value => {
  if (value && activeAppStore.appId !== value) {
    activeAppStore.appId = value
    activeAppStore.databaseStatus = null
  }
}, { immediate: true })
</script>

<style>
:root {
  --el-color-primary: #0f7cff;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif; background: var(--el-bg-color-page); color: var(--el-text-color-primary); -webkit-font-smoothing: antialiased; }

.app {
  min-height: 100vh;
  max-width: none;
  margin: 0;
  padding: 0;
  background: var(--el-bg-color-page);
  color: var(--el-text-color-primary);
}

/* Header */
.app-header { margin-bottom: 0; background: #24292f; border-bottom: 1px solid #1f2328; color: #fff; }
.login-tools { display: flex; justify-content: flex-end; gap: 8px; margin: 0 auto 28px; padding-top: 34px; max-width: 1180px; }
.header-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.app-header .header-top { max-width: 1280px; margin: 0 auto; padding: 14px 24px; }
.header-top h1 { font-size: 20px; font-weight: 750; letter-spacing: 0; color: #fff; }
.header-desc { display: none; }
.header-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.switch-group { display: flex; gap: 3px; background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.16); border-radius: 6px; padding: 3px; box-shadow: none; }

.console-shell { width: 100%; margin: 0; display: grid; grid-template-columns: 220px minmax(0, 1fr); min-height: calc(100vh - 61px); }
.side-menu { background: var(--el-bg-color); padding: 18px 12px; }
.side-menu .el-menu { border-right: none; }
.console-main { min-width: 0; }
.app-context { display: flex; align-items: baseline; gap: 8px; min-height: 64px; max-width: 1280px; margin: 0 auto; padding: 18px 24px; border-bottom: 1px solid var(--el-border-color); background: var(--el-bg-color-page); color: var(--el-text-color-secondary); font-size: 13px; }
.app-context strong { color: var(--el-text-color-primary); font-size: 20px; font-weight: 650; }
.console-main .app-context { max-width: none; padding: 18px 24px; margin: 0; }

.search-view,
.llm-view,
.debug-view,
.upload-view,
.traces-view,
.logs-view,
.database-view,
.config-view,
.apps-view {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px 24px 40px;
}

/* Login */
.login-view { min-height: 56vh; display: grid; place-items: center; }
.login-card { width: min(420px, 100%); display: grid; gap: 14px; background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 6px; padding: 26px; box-shadow: none; }
.login-card h2 { font-size: 20px; color: var(--el-text-color-primary); margin-bottom: 6px; }
.login-card p { font-size: 13px; color: var(--el-text-color-secondary); }

/* Upload */
.upload-card,
.files-card,
.chunks-card { background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 6px; padding: 20px 24px; margin-bottom: 20px; box-shadow: none; }
.upload-icon { color: var(--el-color-primary); margin-bottom: 12px; display: flex; justify-content: center; }
.upload-title { font-size: 15px; font-weight: 500; color: var(--el-text-color-primary); margin-bottom: 4px; }
.upload-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.upload-options { display: grid; grid-template-columns: 1fr; gap: 8px; margin-top: 10px; }
.upload-actions { display: grid; grid-template-columns: 1fr; gap: 8px; }
.upload-feedback { font-size: 13px; margin-top: 8px; padding: 6px 12px; border-radius: 8px; }
.upload-feedback.error { color: var(--el-color-danger); background: rgba(245,106,0,.12); }

.docs-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.docs-head-main { min-width: 0; display: flex; align-items: center; gap: 14px; }
.docs-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.docs-head h2 { font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); }
.docs-count { font-size: 12px; font-weight: 500; color: var(--el-text-color-secondary); background: var(--el-fill-color); padding: 0 8px; min-width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; border-radius: 10px; }
.database-empty-state { min-height: 420px; display: grid; place-items: center; gap: 12px; background: transparent; }
.database-create-btn { width: min(280px, 100%); height: 56px; font-size: 16px; font-weight: 700; }
.database-delete-btn { margin-left: auto; }
.docs-empty { font-size: 13px; color: var(--el-text-color-secondary); text-align: center; padding: 28px 0; }
.chunk-filter { display: grid; grid-template-columns: 64px minmax(0, 1fr) 64px; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 12px; color: var(--el-text-color-secondary); }
.copy-cell { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) 26px; align-items: center; gap: 6px; }
.chunk-id { min-width: 0; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chunk-content { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--el-text-color-primary); }
.chunk-content-tooltip { max-width: min(720px, 80vw); }
.chunk-content-tooltip-body { white-space: pre-wrap; word-break: break-word; max-height: 420px; overflow: auto; line-height: 1.55; }
.table-parts { display: grid; gap: 12px; max-height: 62vh; overflow: auto; }
.table-part { border: 1px solid var(--el-border-color); border-radius: 6px; padding: 10px 12px; background: var(--el-fill-color-light); }
.table-part-head { display: flex; gap: 14px; margin-bottom: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.table-part pre { margin: 0; white-space: pre-wrap; word-break: break-word; font: 13px/1.6 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color: var(--el-text-color-primary); }

/* Monitor */
.monitor-section { background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 6px; padding: 18px 22px; margin-bottom: 20px; box-shadow: none; }
.monitor-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.monitor-head h2 { font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); }
.monitor-head p { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 3px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.page-head h2 { font-size: 20px; font-weight: 650; color: var(--el-text-color-primary); margin-bottom: 4px; }
.page-head p { font-size: 13px; color: var(--el-text-color-secondary); }
.node-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }
.node-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.node-head > div { min-width: 0; }
.node-head p { margin-top: 3px; font-size: 12px; color: var(--el-text-color-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-summary { margin-bottom: 12px; font-size: 12px; color: var(--el-text-color-secondary); }
.log-filters { display: flex; align-items: center; gap: 8px; }
.log-filter { width: 180px; }
.log-time-range, .trace-time-range { width: 360px; }
.monitor-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.monitor-grid + .monitor-block { margin-top: 18px; }
.monitor-section > .monitor-block + .monitor-block { margin-top: 18px; }
.config-grid { display: grid; grid-template-columns: 1fr; gap: 14px 18px; }
.config-panel { min-width: 0; overflow: hidden; display: grid; gap: 8px; }
.config-panel-title { font-size: 12px; font-weight: 600; color: var(--el-text-color-primary); }
.monitor-block { min-width: 0; border: 1px solid var(--el-border-color); border-radius: 6px; padding: 12px; background: var(--el-fill-color-light); }
.trace-block { grid-column: 1 / -1; }
.block-title { font-size: 12px; font-weight: 600; color: var(--el-text-color-secondary); margin-bottom: 10px; }
.component-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.status-legend { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; color: var(--el-text-color-secondary); font-size: 11px; font-weight: 500; }
.status-legend span { display: inline-flex; align-items: center; gap: 4px; }
.component-list { display: grid; gap: 7px; }
.component-row { display: grid; grid-template-columns: 8px minmax(92px, auto) minmax(0, 1fr); align-items: center; gap: 7px; font-size: 12px; color: var(--el-text-color-secondary); min-width: 0; }
.component-row strong { color: var(--el-text-color-primary); font-weight: 500; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.component-name { color: var(--el-text-color-secondary); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--el-text-color-placeholder); }
.status-dot.ready { background: var(--el-color-success); }
.status-dot.disabled { background: var(--el-text-color-placeholder); }
.status-dot.error { background: var(--el-color-danger); }
.kv-list { min-width: 0; display: grid; gap: 7px; }
.kv-list div { min-width: 0; display: grid; grid-template-columns: minmax(120px, 1fr) minmax(0, 1.2fr); align-items: center; gap: 12px; font-size: 12px; color: var(--el-text-color-secondary); }
.kv-list span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kv-list strong { min-width: 0; color: var(--el-text-color-primary); font-weight: 500; text-align: right; overflow-wrap: anywhere; }

.trace-table-wrap { overflow-x: auto; }
.apps-table-wrap { max-height: 360px; overflow: auto; }
.traces-table .el-table__header .cell { white-space: nowrap; }
.trace-query { color: var(--el-text-color-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-stage-cell { display: grid; gap: 2px; min-width: 0; line-height: 1.15; }
.trace-stage-cell strong { font-size: 12px; font-weight: 600; color: var(--el-text-color-primary); }
.trace-stage-cell small { font-size: 10px; color: var(--el-text-color-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-note { font-weight: 500; color: var(--el-text-color-placeholder); }
.trace-empty { font-size: 12px; color: var(--el-text-color-secondary); padding: 18px 0; text-align: center; }
.error-text { color: var(--el-color-danger); }
.logs-box { height: 520px; overflow: auto; margin: 0; border: 1px solid var(--el-border-color); border-radius: 9px; background: #0f1720; color: #d8e2ee; padding: 12px; font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; word-break: break-word; }
html.dark .logs-box { background: #050b13; color: #d6e4f2; }

.job-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.app-create-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 8px; margin-bottom: 12px; }
.app-create-form .el-form-item { margin-bottom: 0; }
.app-row-actions { display: flex; gap: 8px; }

/* Search */
.search-section { position: sticky; bottom: 0; background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 6px; padding: 20px 24px; margin-bottom: 20px; box-shadow: none; }
.search-row-1 { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.search-row-2 { margin-bottom: 10px; }
.search-row-3 { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.scope-controls { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; width: 100%; }
.scope-title { width: 76px; font-size: 13px; color: var(--el-text-color-secondary); white-space: nowrap; }
.scopes { flex: 1; }
.search-input-wrap { flex: 1; display: flex; gap: 8px; }
.topk-control { display: flex; align-items: center; gap: 6px; }
.topk-label { font-size: 13px; color: var(--el-text-color-secondary); }
.rerank-control { margin-right: 8px; }
.fetchk-control { display: flex; align-items: center; gap: 6px; }
.cand-label { font-size: 13px; color: var(--el-text-color-secondary); }

/* Results */
.results-section { background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 6px; padding: 0 24px; box-shadow: none; margin-bottom: 20px; }
.results-bar { display: flex; align-items: center; gap: 16px; padding: 16px 0; border-bottom: 1px solid var(--el-border-color); }
.results-count { font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); }
.results-mode,
.results-balance,
.results-elapsed { font-size: 12px; color: var(--el-text-color-secondary); }
.result-card { padding: 18px 0; border-bottom: 1px solid var(--el-border-color); }
.result-card:last-child { border-bottom: none; }
.result-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.result-file { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--el-text-color-secondary); flex: 1; overflow: hidden; }
.result-file span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-file svg { stroke: var(--el-text-color-secondary); }
.result-score { font-size: 12px; color: var(--el-text-color-secondary); font-variant-numeric: tabular-nums; white-space: nowrap; }
.result-table-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.result-body { font-size: 14px; line-height: 1.8; color: var(--el-text-color-primary); }
.no-results { text-align: center; padding: 48px 24px; }
.no-results p { font-size: 14px; color: var(--el-text-color-secondary); }
.no-results-hint { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 6px; }

@media (max-width: 760px) {
  .console-shell { display: block; }
  .side-menu { border-right: 0; border-bottom: 1px solid var(--el-border-color); padding: 10px 16px; }
  .header-top { flex-direction: column; }
  .header-actions { justify-content: flex-start; }
  .monitor-grid,
  .node-grid,
  .config-grid,
  .app-create { grid-template-columns: 1fr; }
  .log-filters { width: 100%; flex-direction: column; align-items: stretch; }
  .log-filter { width: 100%; }
  .log-time-range, .trace-time-range { width: 100%; }
  .search-input-wrap { flex-direction: column; }
  .results-bar { flex-wrap: wrap; gap: 8px 12px; }
}
</style>
