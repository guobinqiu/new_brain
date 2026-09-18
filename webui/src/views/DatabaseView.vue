<template>
  <main class="database-view">
    <div v-if="appId && databaseStatus && !databaseStatus.exists" class="database-empty-state">
      <el-button
        type="primary"
        size="large"
        class="database-create-btn"
        :loading="databaseInitializing"
        :disabled="databaseInitializing"
        @click="initializeDatabase"
      >
        {{ t('database.initialize') }}
      </el-button>
    </div>

    <div v-else-if="appId && databaseStatus?.exists" class="chunks-card">
      <div class="docs-head">
        <div class="docs-head-main">
          <div class="docs-title">
            <h2>{{ t('database.indexData') }}</h2>
          </div>
        </div>
        <el-button type="danger" class="database-delete-btn" :loading="databaseDeleting" @click="deleteDatabase">{{ t('database.delete') }}</el-button>
      </div>
      <div class="chunk-filter">
        <span>{{ t('database.fileIds') }}</span>
        <el-input v-model.trim="databaseFileIdsText" :placeholder="t('database.fileIdsPlaceholder')" @keyup.enter="fetchActiveChunks" />
        <el-button :disabled="!appId || activeChunksLoading" @click="fetchActiveChunks">{{ t('database.query') }}</el-button>
      </div>
      <div v-if="activeChunks.length === 0 && !activeChunksLoading" class="docs-empty">{{ t('database.vectorEmpty') }}</div>
      <template v-else>
        <el-table
          ref="chunksTableRef"
          :data="activeChunks"
          style="width: 100%"
          max-height="420"
          v-loading="activeChunksLoading"
          @scroll="onChunksScroll"
        >
          <el-table-column prop="id" :label="t('database.chunkId')" min-width="140" show-overflow-tooltip />
          <el-table-column :label="t('database.fileId')" min-width="170" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="copy-cell">
                <span class="chunk-id">{{ row.file_id }}</span>
                <el-button :icon="CopyDocument" circle size="small" @click.stop="copyText(row.file_id)" />
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('database.s3Url')" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="copy-cell">
                <span class="chunk-id">{{ row.s3_url }}</span>
                <el-button :icon="CopyDocument" circle size="small" @click.stop="copyText(row.s3_url)" />
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="filename" :label="t('database.filename')" min-width="120" show-overflow-tooltip />
          <el-table-column :label="t('database.createdAt')" min-width="150">
            <template #default="{ row }">{{ shortTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="chunk_index" :label="t('database.chunkIndex')" min-width="120" />
          <el-table-column :label="t('database.content')" min-width="260">
            <template #default="{ row }">
              <div class="copy-cell">
                <el-tooltip placement="top" popper-class="chunk-content-tooltip">
                  <template #content>
                    <div class="chunk-content-tooltip-body">{{ row.content }}</div>
                  </template>
                  <span class="chunk-content">{{ row.content }}</span>
                </el-tooltip>
                <el-button :icon="CopyDocument" circle size="small" @click.stop="copyText(row.content)" />
              </div>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>
  </main>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { CopyDocument } from '@element-plus/icons-vue'
import axios from '../utils/api'
import { useActiveAppStore } from '../stores/activeApp'
import { errorMessage, showToast } from '../utils/toast'
import { confirmBox } from '../utils/messageBox'
import { copyText, shortTime, parseFileIds } from '../utils/format'

const API = '/api/rag'
const { t } = useI18n()
const activeAppStore = useActiveAppStore()
const { appId, databaseStatus } = storeToRefs(activeAppStore)
const route = useRoute()
const currentAppId = computed(() => route.params.app_id || appId.value)

const databaseFileIdsText = ref('')
const databaseAppliedFileIdsText = ref('')
const chunks = ref([])
const chunksCursor = ref(null)
const chunksHasMore = ref(false)
const chunksLoading = ref(false)
const chunksLoaded = ref(false)
const databaseInitializing = ref(false)
const databaseDeleting = ref(false)
const chunksTableRef = ref(null)
let statusRequestId = 0
let chunksRequestId = 0
let viewActive = true

const activeChunks = computed(() => chunks.value)
const activeChunksLoading = computed(() => chunksLoading.value)

async function fetchDatabaseStatus() {
  const requestId = ++statusRequestId
  if (!currentAppId.value) {
    activeAppStore.databaseStatus = null
    return
  }
  try {
    const res = await axios.get(`${API}/apps/${currentAppId.value}/database`)
    if (requestId !== statusRequestId) return
    activeAppStore.databaseStatus = res.data
  } catch (err) {
    if (requestId !== statusRequestId) return
    activeAppStore.databaseStatus = null
    showToast('error', errorMessage(err))
  }
}

async function initializeDatabase() {
  if (!currentAppId.value) return
  if (databaseInitializing.value) return
  databaseInitializing.value = true
  try {
    await axios.post(`${API}/apps/${currentAppId.value}/database`)
    showToast('success', t('database.initialized', { appId: currentAppId.value }))
    await fetchDatabaseStatus()
    await fetchActiveChunks()
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    databaseInitializing.value = false
  }
}

async function deleteDatabase() {
  if (!currentAppId.value || !activeAppStore.databaseStatus?.exists || databaseDeleting.value) return
  const deletedAppId = currentAppId.value
  try {
    await confirmBox(t, t('database.deleteConfirm', { appId: deletedAppId }), t('database.delete'), { type: 'warning' })
  } catch {
    return
  }
  databaseDeleting.value = true
  try {
    await axios.delete(`${API}/apps/${deletedAppId}/database`)
    showToast('success', t('database.deleted', { appId: deletedAppId }))
    if (!viewActive || currentAppId.value !== deletedAppId) return
    statusRequestId++
    activeAppStore.databaseStatus = { app_id: deletedAppId, exists: false }
    resetChunks()
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    databaseDeleting.value = false
  }
}

async function fetchActiveChunks() {
  if (!currentAppId.value) {
    resetChunks()
    return
  }
  databaseAppliedFileIdsText.value = databaseFileIdsText.value
  resetChunks()
  await fetchNextChunks()
}

function resetChunks() {
  chunksRequestId++
  chunksLoading.value = false
  chunks.value = []
  chunksCursor.value = null
  chunksHasMore.value = false
  chunksLoaded.value = false
}

async function fetchNextChunks() {
  if (!currentAppId.value) return
  if (chunksLoading.value) return
  const requestId = ++chunksRequestId
  chunksLoading.value = true
  try {
    const body = { limit: 50 }
    if (chunksCursor.value) body.cursor = chunksCursor.value
    if (currentAppId.value) body.app_id = currentAppId.value
    const fileIds = parseFileIds(databaseAppliedFileIdsText.value)
    if (fileIds.length) body.file_ids = fileIds
    const res = await axios.post(`${API}/chunks`, body)
    if (requestId !== chunksRequestId) return
    chunks.value = chunks.value.concat(res.data.chunks || [])
    chunksCursor.value = res.data.next_cursor || null
    chunksHasMore.value = Boolean(res.data.has_more)
    chunksLoaded.value = true
    if (!chunksCursor.value) await fetchDatabaseStatus()
  }
  catch (err) { showToast('error', errorMessage(err)) }
  finally { if (requestId === chunksRequestId) chunksLoading.value = false }
}

function onChunksScroll(event) {
  // el-table 的 scroll 事件 payload 为 { scrollTop, scrollLeft }（非原生事件），
  // 触底判断需要读取内部滚动容器（ElScrollbar wrapRef）的 clientHeight/scrollHeight
  const wrap = chunksTableRef.value?.scrollBarRef?.wrapRef
  if (!wrap) return
  const scrollTop = event?.scrollTop ?? wrap.scrollTop
  if (scrollTop + wrap.clientHeight >= wrap.scrollHeight - 24 && chunksHasMore.value) {
    fetchNextChunks()
  }
}

onMounted(async () => {
  await fetchDatabaseStatus()
  if (activeAppStore.databaseStatus?.exists) await fetchActiveChunks()
})

onBeforeUnmount(() => {
  viewActive = false
  statusRequestId++
  chunksRequestId++
})

watch(currentAppId, async () => {
  resetChunks()
  await fetchDatabaseStatus()
  if (activeAppStore.databaseStatus?.exists) await fetchActiveChunks()
})
</script>

<style scoped>
</style>
