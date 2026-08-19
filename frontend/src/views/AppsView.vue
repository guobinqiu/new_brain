<template>
  <main class="apps-view">
    <div class="monitor-section">
      <div class="monitor-head">
        <div>
          <h2>{{ t('apps.title') }}</h2>
          <p>{{ t('apps.desc') }}</p>
        </div>
      </div>
      <form class="app-create">
        <el-input v-model.trim="newAppId" :placeholder="t('apps.appIdPlaceholder')" @keyup.enter="createApp" />
        <el-button type="primary" :loading="creatingApp" @click="createApp">{{ creatingApp ? t('common.loading') : t('apps.create') }}</el-button>
      </form>
      <div v-if="apps.length" class="trace-table-wrap apps-table-wrap">
        <el-table :data="apps" style="width: 100%">
          <el-table-column prop="app_id" label="app_id" min-width="160" show-overflow-tooltip />
          <el-table-column label="access_key" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="copy-cell">
                <span class="chunk-id" :title="row.access_key">{{ row.access_key }}</span>
                <el-button size="small" @click="copyText(row.access_key)">{{ t('common.copy') }}</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="secret_key" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="copy-cell">
                <span class="chunk-id" :title="row.secret_key">{{ row.secret_key }}</span>
                <el-button size="small" @click="copyText(row.secret_key)">{{ t('common.copy') }}</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" width="184">
            <template #default="{ row }">
              <div class="app-row-actions">
                <el-button type="primary" size="small" @click="selectApp(row)">{{ t('apps.enter') }}</el-button>
                <el-button type="danger" size="small" @click="deleteApp(row)">{{ t('common.delete') }}</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div v-else class="trace-empty">{{ t('apps.empty') }}</div>
    </div>
  </main>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'
import { useActiveAppStore } from '../stores/activeApp'
import { useAppsStore } from '../stores/apps'
import { showToast } from '../utils/toast'
import { ElMessageBox } from 'element-plus'
import { copyText } from '../utils/format'

const API = '/api'
const router = useRouter()
const { t } = useI18n()
const activeAppStore = useActiveAppStore()

const appsStore = useAppsStore()
const { apps } = storeToRefs(appsStore)

const newAppId = ref('')
const creatingApp = ref(false)

async function createApp() {
  if (!newAppId.value || creatingApp.value) return
  creatingApp.value = true
  try {
    const res = await axios.post(`${API}/apps`, { app_id: newAppId.value })
    showToast('success', t('apps.created', { appId: res.data.app_id }))
    newAppId.value = ''
    await appsStore.fetchApps()
  } catch (err) {
    showToast('error', err.response?.data?.detail || err.message)
  } finally {
    creatingApp.value = false
  }
}

async function deleteApp(app) {
  if (!app?.app_id) return
  try {
    await ElMessageBox.confirm(
      t('apps.deleteConfirm', { appId: app.app_id }),
      t('common.delete'),
      { type: 'warning', confirmButtonText: t('common.delete') }
    )
  } catch {
    return
  }
  try {
    await axios.delete(`${API}/apps/${encodeURIComponent(app.app_id)}`)
    showToast('success', t('apps.deleted', { appId: app.app_id }))
    if (activeAppStore.appId === app.app_id) {
      activeAppStore.appId = ''
      activeAppStore.databaseStatus = null
    }
    await appsStore.fetchApps()
  } catch (err) {
    showToast('error', err.response?.data?.detail || err.message)
  }
}

function selectApp(app) {
  if (!app?.app_id) return
  activeAppStore.appId = app.app_id
  router.push('/database')
}

onMounted(() => appsStore.fetchApps())
</script>
