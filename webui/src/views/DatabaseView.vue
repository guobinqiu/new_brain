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
          <el-radio-group v-model="activeDataSource" size="small" @change="onDataSourceChange">
            <el-radio-button value="vector">{{ t('database.vectorStore') }}</el-radio-button>
            <el-radio-button v-if="searchIndexAvailable" value="search">{{ t('database.searchIndex') }}</el-radio-button>
          </el-radio-group>
        </div>
        <el-button type="danger" class="database-delete-btn" @click="deleteDatabase">{{ t('database.delete') }}</el-button>
      </div>
      <div class="chunk-filter">
        <span>{{ t('database.fileIds') }}</span>
        <el-input v-model.trim="databaseFileIdsText" :placeholder="t('database.fileIdsPlaceholder')" @keyup.enter="fetchActiveChunks" />
        <el-button :disabled="!appId || activeChunksLoading" @click="fetchActiveChunks">{{ t('database.query') }}</el-button>
      </div>
      <div v-if="activeDataSource === 'search' && !searchIndexAvailable" class="docs-empty">{{ t('database.searchIndexDisabled') }}</div>
      <div v-else-if="activeChunks.length === 0 && !activeChunksLoading" class="docs-empty">{{ activeDataSource === 'vector' ? t('database.vectorEmpty') : t('database.searchIndexEmpty') }}</div>
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
          <el-table-column prop="chunk_index" :label="t('database.chunkIndex')" width="92" />
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
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'
import axios from '../utils/api'
import { useActiveAppStore } from '../stores/activeApp'
import { errorMessage, showToast } from '../utils/toast'
import { copyText, shortTime, parseFileIds } from '../utils/format'

const API = '/api/open/rag'
const { t } = useI18n()
const activeAppStore = useActiveAppStore()
const { appId, databaseStatus } = storeToRefs(activeAppStore)
const route = useRoute()
const currentAppId = computed(() => route.params.app_id || appId.value)

const databaseFileIdsText = ref('')
const databaseAppliedFileIdsText = ref('')
const activeDataSource = ref('vector')
const chunks = ref([])
const chunksCursor = ref(null)
const chunksHasMore = ref(false)
const chunksLoading = ref(false)
const chunksLoaded = ref(false)
const sparseChunks = ref([])
const sparseChunksCursor = ref(null)
const sparseChunksHasMore = ref(false)
const sparseChunksLoading = ref(false)
const sparseChunksLoaded = ref(false)
const databaseInitializing = ref(false)
const chunksTableRef = ref(null)
const capabilities = ref({})

const activeChunks = computed(() => activeDataSource.value === 'vector' ? chunks.value : sparseChunks.value)
const activeChunksLoading = computed(() => activeDataSource.value === 'vector' ? chunksLoading.value : sparseChunksLoading.value)
const searchIndexAvailable = computed(() => capabilities.value.search_index === true)

async function fetchConfig() {
  try {
    const res = await axios.get(`${API}/config`)
    capabilities.value = res.data?.capabilities || {}
    if (!searchIndexAvailable.value && activeDataSource.value === 'search') {
      activeDataSource.value = 'vector'
      resetSparseChunks()
    }
  } catch (err) {
    capabilities.value = {}
    if (activeDataSource.value === 'search') {
      activeDataSource.value = 'vector'
      resetSparseChunks()
    }
  }
}

async function fetchDatabaseStatus() {
  if (!currentAppId.value) {
    activeAppStore.databaseStatus = null
    return
  }
  try {
    const res = await axios.get(`${API}/apps/${currentAppId.value}/database`)
    activeAppStore.databaseStatus = res.data
  } catch (err) {
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
  if (!currentAppId.value || !activeAppStore.databaseStatus?.exists) return
  try {
    await ElMessageBox.confirm(t('database.deleteConfirm', { appId: currentAppId.value }), t('database.delete'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await axios.delete(`${API}/apps/${currentAppId.value}/database`)
    showToast('success', t('database.deleted', { appId: currentAppId.value }))
    resetChunks()
    resetSparseChunks()
    await fetchDatabaseStatus()
  } catch (err) {
    showToast('error', errorMessage(err))
  }
}

async function fetchActiveChunks() {
  if (!currentAppId.value) {
    resetChunks()
    resetSparseChunks()
    return
  }
  databaseAppliedFileIdsText.value = databaseFileIdsText.value
  if (activeDataSource.value === 'search') {
    resetSparseChunks()
    if (!searchIndexAvailable.value) {
      sparseChunksLoaded.value = true
      return
    }
    await fetchNextSparseChunks()
    return
  }
  resetChunks()
  await fetchNextChunks()
}

function resetChunks() {
  chunks.value = []
  chunksCursor.value = null
  chunksHasMore.value = false
  chunksLoaded.value = false
}

function resetSparseChunks() {
  sparseChunks.value = []
  sparseChunksCursor.value = null
  sparseChunksHasMore.value = false
  sparseChunksLoaded.value = false
}

async function fetchNextChunks() {
  if (!currentAppId.value) return
  if (chunksLoading.value) return
  chunksLoading.value = true
  try {
    const body = { limit: 50 }
    if (chunksCursor.value) body.cursor = chunksCursor.value
    if (currentAppId.value) body.app_id = currentAppId.value
    const fileIds = parseFileIds(databaseAppliedFileIdsText.value)
    if (fileIds.length) body.file_ids = fileIds
    const res = await axios.post(`${API}/chunks`, body)
    chunks.value = chunks.value.concat(res.data.chunks || [])
    chunksCursor.value = res.data.next_cursor || null
    chunksHasMore.value = Boolean(res.data.has_more)
    chunksLoaded.value = true
    if (!chunksCursor.value) await fetchDatabaseStatus()
  }
  catch (err) { console.error(err) }
  finally { chunksLoading.value = false }
}

async function fetchNextSparseChunks() {
  if (!currentAppId.value) return
  if (sparseChunksLoading.value) return
  sparseChunksLoading.value = true
  try {
    const body = { limit: 50 }
    if (sparseChunksCursor.value) body.cursor = sparseChunksCursor.value
    if (currentAppId.value) body.app_id = currentAppId.value
    const fileIds = parseFileIds(databaseAppliedFileIdsText.value)
    if (fileIds.length) body.file_ids = fileIds
    const res = await axios.post(`${API}/sparse/chunks`, body)
    sparseChunks.value = sparseChunks.value.concat(res.data.chunks || [])
    sparseChunksCursor.value = res.data.next_cursor || null
    sparseChunksHasMore.value = Boolean(res.data.has_more)
    sparseChunksLoaded.value = true
  }
  catch (err) { console.error(err) }
  finally { sparseChunksLoading.value = false }
}

async function onDataSourceChange() {
  if (activeDataSource.value === 'search' && !sparseChunksLoaded.value) await fetchActiveChunks()
  if (activeDataSource.value === 'vector' && !chunksLoaded.value) await fetchActiveChunks()
}

function onChunksScroll(event) {
  // el-table 的 scroll 事件 payload 为 { scrollTop, scrollLeft }（非原生事件），
  // 触底判断需要读取内部滚动容器（ElScrollbar wrapRef）的 clientHeight/scrollHeight
  const wrap = chunksTableRef.value?.scrollBarRef?.wrapRef
  if (!wrap) return
  const scrollTop = event?.scrollTop ?? wrap.scrollTop
  if (activeDataSource.value === 'search' && scrollTop + wrap.clientHeight >= wrap.scrollHeight - 24 && sparseChunksHasMore.value) {
    fetchNextSparseChunks()
    return
  }
  if (scrollTop + wrap.clientHeight >= wrap.scrollHeight - 24 && chunksHasMore.value) {
    fetchNextChunks()
  }
}

onMounted(async () => {
  await fetchConfig()
  await fetchDatabaseStatus()
  if (activeAppStore.databaseStatus?.exists) await fetchActiveChunks()
  window.addEventListener('focus', refreshConfig)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  window.removeEventListener('focus', refreshConfig)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

watch(currentAppId, async () => {
  resetChunks()
  resetSparseChunks()
  await fetchConfig()
  await fetchDatabaseStatus()
  if (activeAppStore.databaseStatus?.exists) await fetchActiveChunks()
})

async function refreshConfig() {
  await fetchConfig()
}

function onVisibilityChange() {
  if (document.visibilityState === 'visible') refreshConfig()
}
</script>

<style scoped>
</style>
