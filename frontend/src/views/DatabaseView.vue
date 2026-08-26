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
        <div class="docs-title">
          <h2>{{ t('database.chunks') }}</h2>
        </div>
        <el-button type="danger" class="database-delete-btn" @click="deleteDatabase">{{ t('database.delete') }}</el-button>
      </div>
      <div class="chunk-filter">
        <span>{{ t('database.fileIds') }}</span>
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
          <el-table-column :label="t('database.contentType')" width="96">
            <template #default="{ row }">{{ row.content_type || '-' }}</template>
          </el-table-column>
          <el-table-column :label="t('database.tableId')" min-width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ row.table_id || '-' }}</template>
          </el-table-column>
          <el-table-column :label="t('database.tablePartIndex')" width="120">
            <template #default="{ row }">
              {{ row.table_part_index ?? '-' }}
            </template>
          </el-table-column>
          <el-table-column :label="t('database.tablePartCount')" width="120">
            <template #default="{ row }">{{ row.table_part_count ?? '-' }}</template>
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
          <el-table-column :label="t('common.actions')" width="120" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.content_type === 'table' && row.table_id" size="small" @click="openTableParts(row)">{{ t('database.viewTable') }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>
    <el-dialog v-model="tablePartsVisible" :title="tablePartsTitle" width="860px">
      <div v-if="tableParts.length === 0" class="docs-empty">{{ t('database.emptyTableParts') }}</div>
      <div v-else class="table-parts">
        <section v-for="part in tableParts" :key="part.table_part_index" class="table-part">
          <div class="table-part-head">
            <span>{{ t('database.tablePartIndex') }}: {{ part.table_part_index }}</span>
            <span>{{ t('database.chunkIndex') }}: {{ part.chunk_index }}</span>
          </div>
          <pre>{{ part.content }}</pre>
        </section>
      </div>
    </el-dialog>
  </main>
</template>

<script setup>
import { computed, ref, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'
import axios from '../utils/api'
import { useActiveAppStore } from '../stores/activeApp'
import { errorMessage, showToast } from '../utils/toast'
import { copyText, shortTime, parseFileIds } from '../utils/format'

const API = '/api'
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
const databaseInitializing = ref(false)
const chunksTableRef = ref(null)
const tablePartsVisible = ref(false)
const tableParts = ref([])
const tablePartsTitle = ref('')

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
    await fetchChunks()
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
    chunks.value = []
    chunksCursor.value = null
    chunksHasMore.value = false
    await fetchDatabaseStatus()
  } catch (err) {
    showToast('error', errorMessage(err))
  }
}

async function fetchChunks() {
  if (!currentAppId.value) {
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

async function openTableParts(row) {
  if (!currentAppId.value || !row.file_id || !row.table_id) return
  try {
    const res = await axios.post(`${API}/tables/parts`, {
      app_id: currentAppId.value,
      file_id: row.file_id,
      table_id: row.table_id,
    })
    tableParts.value = res.data.parts || []
    tablePartsTitle.value = `${row.file_id} · ${row.table_id}`
    tablePartsVisible.value = true
  } catch (err) {
    showToast('error', errorMessage(err))
  }
}

onMounted(async () => {
  await fetchDatabaseStatus()
  if (activeAppStore.databaseStatus?.exists) await fetchChunks()
})

watch(currentAppId, async () => {
  chunks.value = []
  chunksCursor.value = null
  chunksHasMore.value = false
  await fetchDatabaseStatus()
  if (activeAppStore.databaseStatus?.exists) await fetchChunks()
})
</script>
