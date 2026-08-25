<template>
  <main class="apps-view">
    <div class="monitor-section">
      <div class="monitor-head">
        <div>
          <h2>{{ t('apps.title') }}</h2>
          <p>{{ t('apps.desc') }}</p>
        </div>
      </div>
      <form class="app-create" @submit.prevent="createApp">
        <el-input v-model.trim="newAppId" :placeholder="t('apps.appIdPlaceholder')" />
        <el-button type="primary" native-type="submit" :loading="creatingApp">{{ creatingApp ? t('common.loading') : t('apps.create') }}</el-button>
      </form>
      <div v-if="apps.length" class="trace-table-wrap apps-table-wrap">
        <el-table :data="apps" style="width: 100%">
          <el-table-column prop="app_id" label="app_id" min-width="160" show-overflow-tooltip />
          <el-table-column label="access_key" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="copy-cell">
                <span class="chunk-id">{{ row.access_key }}</span>
                <el-button :icon="CopyDocument" circle size="small" @click.stop="copyText(row.access_key)" />
              </div>
            </template>
          </el-table-column>
          <el-table-column label="secret_key" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="copy-cell">
                <span class="chunk-id">{{ row.secret_key }}</span>
                <el-button :icon="CopyDocument" circle size="small" @click.stop="copyText(row.secret_key)" />
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
import { errorMessage, showToast } from '../utils/toast'
import { ElMessageBox } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'
import { copyText } from '../utils/format'

const API = '/api'
const router = useRouter()
const { t } = useI18n()
const activeAppStore = useActiveAppStore()

const appsStore = useAppsStore()
const { apps } = storeToRefs(appsStore)

const APP_ID_PATTERN = /^[A-Za-z][A-Za-z0-9_]{1,63}$/
const newAppId = ref('')
const creatingApp = ref(false)

async function createApp() {
  if (!newAppId.value || creatingApp.value) return
  if (!APP_ID_PATTERN.test(newAppId.value)) {
    showToast('error', t('apps.appIdRule'))
    return
  }
  creatingApp.value = true
  try {
    const res = await axios.post(`${API}/apps`, { app_id: newAppId.value })
    showToast('success', t('apps.created', { appId: res.data.app_id }))
    newAppId.value = ''
    await appsStore.fetchApps()
  } catch (err) {
    showToast('error', errorMessage(err))
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
    await axios.delete(`${API}/apps/${app.app_id}`)
    showToast('success', t('apps.deleted', { appId: app.app_id }))
    if (activeAppStore.appId === app.app_id) {
      activeAppStore.appId = ''
      activeAppStore.databaseStatus = null
    }
    await appsStore.fetchApps()
  } catch (err) {
    showToast('error', errorMessage(err))
  }
}

function selectApp(app) {
  if (!app?.app_id) return
  activeAppStore.appId = app.app_id
  router.push('/database')
}

onMounted(() => appsStore.fetchApps())
</script>
