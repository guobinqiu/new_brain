<template>
  <main class="database-view">
    <div v-if="appId && databaseStatus && !databaseStatus.exists" class="database-empty-state">
      <el-button type="primary" size="large" class="database-create-btn" @click="initializeDatabase">{{ t('database.initialize') }}</el-button>
    </div>

    <div v-else-if="appId && databaseStatus?.exists" class="chunks-card">
      <div class="docs-head">
        <div class="docs-title">
          <h2>{{ t('database.chunks') }}</h2>
          <span class="docs-count">{{ chunks.length }}{{ chunksHasMore ? '+' : '' }}</span>
        </div>
        <el-button type="danger" class="database-delete-btn" :disabled="!databaseStatus?.empty" @click="deleteDatabase">{{ t('database.delete') }}</el-button>
      </div>
      <div class="chunk-filter">
        <span>File IDs</span>
        <el-input v-model.trim="databaseFileIdsText" :placeholder="t('database.fileIdsPlaceholder')" @keyup.enter="fetchChunks" />
        <el-button :disabled="!appId || chunksLoading" @click="fetchChunks">{{ t('database.query') }}</el-button>
      </div>
      <div v-if="chunks.length === 0 && !chunksLoading" class="docs-empty">{{ t('database.empty') }}</div>
      <template v-else>
        <el-table
          ref="chunksTableRef"
          :data="chunks"
          style="width: 100%"
          max-height="420"
          v-loading="chunksLoading"
          @scroll="onChunksScroll"
        >
          <el-table-column prop="id" label="chunk_id" min-width="140" show-overflow-tooltip />
          <el-table-column label="file_id" min-width="170" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="copy-cell">
                <span class="chunk-id" :title="row.file_id">{{ row.file_id }}</span>
                <el-button size="small" @click="copyText(row.file_id)">{{ t('common.copy') }}</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="s3_url" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="copy-cell">
                <span class="chunk-id" :title="row.s3_url">{{ row.s3_url }}</span>
                <el-button size="small" @click="copyText(row.s3_url)">{{ t('common.copy') }}</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="filename" label="filename" min-width="120" show-overflow-tooltip />
          <el-table-column label="created_at" min-width="150">
            <template #default="{ row }">{{ shortTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="chunk_index" label="chunk_index" width="92" />
          <el-table-column label="content" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="copy-cell">
                <span class="chunk-content" :title="row.content">{{ row.content }}</span>
                <el-button size="small" @click="copyText(row.content)">{{ t('common.copy') }}</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <el-button v-if="chunksHasMore && !chunksLoading" class="docs-more" @click="fetchNextChunks">{{ t('common.loadMore') }}</el-button>
      </template>
    </div>
  </main>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import axios from '../utils/api'
import { useActiveAppStore } from '../stores/activeApp'
import { showToast } from '../utils/toast'
import { copyText, shortTime, parseFileIds } from '../utils/format'

const API = '/api'
const { t } = useI18n()
const activeAppStore = useActiveAppStore()
const { appId, databaseStatus } = storeToRefs(activeAppStore)

const databaseFileIdsText = ref('')
const databaseAppliedFileIdsText = ref('')
const chunks = ref([])
const chunksCursor = ref(null)
const chunksHasMore = ref(false)
const chunksLoading = ref(false)
const chunksTableRef = ref(null)

async function fetchDatabaseStatus() {
  if (!activeAppStore.appId) {
    activeAppStore.databaseStatus = null
    return
  }
  try {
    const res = await axios.get(`${API}/apps/${encodeURIComponent(activeAppStore.appId)}/database`)
    activeAppStore.databaseStatus = res.data
  } catch (err) {
    activeAppStore.databaseStatus = null
    showToast('error', err.response?.data?.detail || err.message)
  }
}

async function initializeDatabase() {
  if (!activeAppStore.appId) return
  try {
    await axios.post(`${API}/apps/${encodeURIComponent(activeAppStore.appId)}/database`)
    showToast('success', t('database.initialized', { appId: activeAppStore.appId }))
    await fetchDatabaseStatus()
    await fetchChunks()
  } catch (err) {
    showToast('error', err.response?.data?.detail || err.message)
  }
}

async function deleteDatabase() {
  if (!activeAppStore.appId || !activeAppStore.databaseStatus?.exists || !activeAppStore.databaseStatus?.empty) return
  try {
    await ElMessageBox.confirm(t('database.deleteConfirm', { appId: activeAppStore.appId }), t('database.delete'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await axios.delete(`${API}/apps/${encodeURIComponent(activeAppStore.appId)}/database`)
    showToast('success', t('database.deleted', { appId: activeAppStore.appId }))
    chunks.value = []
    chunksCursor.value = null
    chunksHasMore.value = false
    await fetchDatabaseStatus()
  } catch (err) {
    showToast('error', err.response?.data?.detail || err.message)
  }
}

async function fetchChunks() {
  if (!activeAppStore.appId) {
    chunks.value = []
    chunksCursor.value = null
    chunksHasMore.value = false
    return
  }
  databaseAppliedFileIdsText.value = databaseFileIdsText.value
  chunks.value = []
  chunksCursor.value = null
  chunksHasMore.value = false
  await fetchNextChunks()
}

async function fetchNextChunks() {
  if (!activeAppStore.appId) return
  if (chunksLoading.value) return
  chunksLoading.value = true
  try {
    const body = { limit: 50 }
    if (chunksCursor.value) body.cursor = chunksCursor.value
    if (activeAppStore.appId) body.app_id = activeAppStore.appId
    const fileIds = parseFileIds(databaseAppliedFileIdsText.value)
    if (fileIds.length) body.file_ids = fileIds
    const res = await axios.post(`${API}/chunks`, body)
    chunks.value = chunks.value.concat(res.data.chunks || [])
    chunksCursor.value = res.data.next_cursor || null
    chunksHasMore.value = Boolean(res.data.has_more)
    if (!chunksCursor.value) await fetchDatabaseStatus()
  }
  catch (err) { console.error(err) }
  finally { chunksLoading.value = false }
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
  if (activeAppStore.databaseStatus?.exists) await fetchChunks()
})
</script>
