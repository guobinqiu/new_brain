<template>
  <main class="apps-view">
    <div class="monitor-section">
      <div class="monitor-head">
        <div>
          <h2>{{ t('apps.title') }}</h2>
          <p>{{ t('apps.desc') }}</p>
        </div>
      </div>
      <el-form class="app-create-form" @submit.prevent="createApp">
        <el-form-item>
          <el-input
            v-model.trim="newAppId"
            :placeholder="t('apps.appIdPlaceholder')"
            clearable
          />
        </el-form-item>
        <el-button type="primary" :loading="creating" native-type="submit">{{ t('apps.create') }}</el-button>
      </el-form>
      <div v-if="apps.length" class="trace-table-wrap apps-table-wrap">
        <el-table :data="apps" style="width: 100%">
          <el-table-column prop="app_id" label="app_id" min-width="160" show-overflow-tooltip />
          <el-table-column label="api_key" min-width="360" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="copy-cell">
                <span class="chunk-id">{{ row.api_key }}</span>
                <el-button :icon="CopyDocument" circle size="small" @click.stop="copyText(row.api_key)" />
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" min-width="184">
            <template #default="{ row }">
              <div class="app-row-actions">
                <el-button type="primary" size="small" @click="selectApp(row)">{{ t('apps.enter') }}</el-button>
                <el-button type="danger" size="small" plain @click="deleteApp(row)">{{ t('common.delete') }}</el-button>
                <el-tooltip :content="t('apps.presignConfig')">
                  <el-button :icon="Setting" size="small" :aria-label="t('apps.presignConfig')" @click="editPresign(row)" />
                </el-tooltip>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div v-else class="trace-empty">{{ t('apps.empty') }}</div>
    </div>
    <el-dialog v-model="presignVisible" :title="`${presignAppId} · ${t('apps.presignConfig')}`" width="min(760px, 94vw)">
      <el-input v-model="presignTemplate" type="textarea" :rows="18" :aria-label="t('apps.presignConfig')" />
      <template #footer>
        <el-button type="primary" :loading="savingPresign" @click="savePresign">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useActiveAppStore } from '../stores/activeApp'
import { useAppsStore } from '../stores/apps'
import { CopyDocument, Setting } from '@element-plus/icons-vue'
import axios from '../utils/api'
import { copyText } from '../utils/format'
import { errorMessage, showToast } from '../utils/toast'
import { confirmBox } from '../utils/messageBox'

const router = useRouter()
const { t } = useI18n()
const activeAppStore = useActiveAppStore()

const appsStore = useAppsStore()
const { apps } = storeToRefs(appsStore)
const newAppId = ref('')
const creating = ref(false)
const presignVisible = ref(false)
const presignAppId = ref('')
const presignTemplate = ref('')
const savingPresign = ref(false)

async function editPresign(app) {
  try {
    const response = await axios.get(`/api/rag/apps/${app.app_id}/presign-config`)
    presignAppId.value = app.app_id
    presignTemplate.value = response.data.presign_config
    presignVisible.value = true
  } catch (err) {
    showToast('error', errorMessage(err))
  }
}

async function savePresign() {
  savingPresign.value = true
  try {
    await axios.put(`/api/rag/apps/${presignAppId.value}/presign-config`, presignTemplate.value, {
      headers: { 'Content-Type': 'text/plain' },
    })
    presignVisible.value = false
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    savingPresign.value = false
  }
}

function selectApp(app) {
  if (!app?.app_id) return
  activeAppStore.appId = app.app_id
  router.push(`/apps/${app.app_id}/database`)
}

async function createApp() {
  if (!newAppId.value) {
    showToast('error', t('apps.appIdRule'))
    return
  }
  creating.value = true
  try {
    const created = await appsStore.createApp(newAppId.value)
    newAppId.value = ''
    showToast('success', t('apps.created', { appId: created.app_id }))
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    creating.value = false
  }
}

async function deleteApp(app) {
  if (!app?.app_id) return
  try {
    await confirmBox(t, t('apps.deleteConfirm', { appId: app.app_id }), t('common.delete'), { type: 'warning' })
    await appsStore.deleteApp(app.app_id)
    if (activeAppStore.appId === app.app_id) activeAppStore.appId = ''
    showToast('success', t('apps.deleted', { appId: app.app_id }))
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    showToast('error', errorMessage(err))
  }
}

onMounted(() => appsStore.fetchApps())
</script>
