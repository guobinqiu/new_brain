<template>
  <main class="upload-view">
    <input ref="updateInputRef" type="file" hidden accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.ppt,.pptx" @change="updateSelectedFile" />
    <div class="upload-card">
      <el-upload
        ref="uploadRef"
        drag
        multiple
        :auto-upload="false"
        :show-file-list="false"
        accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.ppt,.pptx"
        :on-change="onFileChange"
      >
        <div @dragover.prevent @drop.prevent="onDrop">
          <div class="upload-icon">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          </div>
          <p class="upload-title">{{ selectedFiles.length ? selectedFiles.map(file => file.name).join('、') : t('upload.choose') }}</p>
          <p class="upload-hint">{{ t('upload.hint') }}</p>
        </div>
      </el-upload>
      <div class="upload-options">
        <div class="upload-actions">
          <el-button type="primary" :disabled="!appId || selectedFiles.length === 0 || uploading" :loading="uploading" @click="uploadSelectedFiles">{{ uploading ? t('upload.uploading') : t('upload.submit') }}</el-button>
        </div>
      </div>
    </div>

    <div class="files-card">
      <div class="docs-head">
        <div class="docs-title">
          <h2>{{ t('upload.files') }}</h2>
          <span class="docs-count">{{ filesTotal }}</span>
        </div>
        <el-button size="small" :loading="filesLoading" @click="fetchFiles">{{ t('common.refresh') }}</el-button>
      </div>
      <div v-if="files.length === 0 && !filesLoading" class="docs-empty">{{ t('upload.empty') }}</div>
      <template v-else>
        <el-table
          ref="filesTableRef"
          :data="files"
          style="width: 100%"
          max-height="360"
          v-loading="filesLoading"
          @scroll="onFilesScroll"
        >
          <el-table-column label="file_id" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="chunk-id">{{ row.id }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="filename" label="filename" min-width="220" show-overflow-tooltip />
          <el-table-column label="s3_url" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="chunk-id">{{ row.s3_url }}</span>
            </template>
          </el-table-column>
          <el-table-column label="created_at" min-width="160">
            <template #default="{ row }">{{ shortTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="status" label="status" min-width="100">
            <template #default="{ row }">{{ updatingFileIds.has(row.id) ? 'indexing' : row.status }}</template>
          </el-table-column>
          <el-table-column label="indexed_at" min-width="160">
            <template #default="{ row }">{{ shortTime(row.indexed_at) }}</template>
          </el-table-column>
          <el-table-column label="error" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ indexErrorMessage(row.error) }}</template>
          </el-table-column>
          <el-table-column prop="size" label="size" min-width="100" />
          <el-table-column :label="t('common.actions')" min-width="210">
            <template #default="{ row }">
              <el-button type="danger" size="small" :disabled="deletingFileId === row.id || retryingFileIds.has(row.id) || updatingFileIds.has(row.id)" @click="deleteFile(row)">{{ deletingFileId === row.id ? t('common.deleting') : t('common.delete') }}</el-button>
              <el-tooltip v-if="row.status === 'failed'" :content="t('common.retry')">
                <el-button :icon="RefreshRight" size="small" :aria-label="t('common.retry')" :loading="retryingFileIds.has(row.id)" :disabled="deletingFileId === row.id || updatingFileIds.has(row.id)" @click="retryFile(row)" />
              </el-tooltip>
              <el-tooltip :content="t('upload.updateFile')">
                <el-button :icon="Upload" size="small" :aria-label="t('upload.updateFile')" :loading="updatingFileIds.has(row.id)" :disabled="deletingFileId === row.id || retryingFileIds.has(row.id) || ['queued', 'indexing'].includes(row.status)" @click="chooseUpdatedFile(row)" />
              </el-tooltip>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>
  </main>
</template>

<script setup>
import { computed, ref, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import axios from '../utils/api'
import { useActiveAppStore } from '../stores/activeApp'
import { errorMessage, indexErrorMessage, showToast } from '../utils/toast'
import { shortTime } from '../utils/format'
import { RefreshRight, Upload } from '@element-plus/icons-vue'

const API = '/api/rag'
const { t } = useI18n()
const activeAppStore = useActiveAppStore()
const { appId } = storeToRefs(activeAppStore)
const route = useRoute()
const currentAppId = computed(() => route.params.app_id || appId.value)

const selectedFiles = ref([])
const uploading = ref(false)
const files = ref([])
const filesTotal = ref(0)
const filesNextCursor = ref(null)
const filesLoading = ref(false)
const deletingFileId = ref(null)
const retryingFileIds = ref(new Set())
const updatingFileIds = ref(new Set())
const updateInputRef = ref(null)
const updateTarget = ref(null)
const uploadRef = ref(null)
const filesTableRef = ref(null)

// el-upload on-change：(uploadFile, uploadFiles)，uploadFiles 为 UploadFile 数组，raw 为原始 File
function onFileChange(file, fileList) {
  selectedFiles.value = fileList.map(item => item.raw).filter(Boolean)
}

// el-upload 在 2.14 无 on-drop prop，拖拽由内部 dragger 触发 on-change；
// 此处保留原模板的原生 drop 兜底（dataTransfer.files）
async function onDrop(e) {
  const files = e.dataTransfer.files
  selectedFiles.value = files.length ? Array.from(files) : []
}

async function uploadSelectedFiles() {
  if (!currentAppId.value) {
    showToast('error', t('upload.selectApp'))
    return
  }
  if (!selectedFiles.value.length || uploading.value) return
  uploading.value = true
  try {
    const uploaded = await uploadFiles(selectedFiles.value)
    if (uploaded) {
      selectedFiles.value = []
      // 清空 el-upload 内部列表，避免下次 on-change 携带已上传的旧文件
      uploadRef.value?.clearFiles()
    }
  } finally {
    uploading.value = false
  }
}

async function uploadFiles(files, fileId = null, targetAppId = currentAppId.value) {
  let submitted = 0
  for (const file of files) {
    const form = new FormData()
    form.append('file', file)
    form.append('app_id', targetAppId)
    if (fileId) form.append('file_id', fileId)
    try {
      const uploadRes = await axios.post(`${API}/upload`, form)
      const body = {
        app_id: targetAppId,
        file_id: uploadRes.data.file_id,
        s3_url: uploadRes.data.s3_url,
        filename: uploadRes.data.filename,
      }
      try {
        const res = await axios.post(`${API}/files`, body)
        if (res.data?.success !== true) {
          showToast('error', `${file.name}: ${indexErrorMessage(res.data)}`)
          continue
        }
      } catch (err) {
        showToast('error', `${file.name}: ${errorMessage(err)}`)
        continue
      }
      submitted++
    } catch (err) {
      showToast('error', `${file.name}: ${errorMessage(err)}`)
    }
  }
  if (currentAppId.value === targetAppId) await fetchFiles()
  if (submitted > 0) {
    showToast('success', t('upload.indexSubmitted', { count: submitted }))
  }
  return submitted > 0
}

function chooseUpdatedFile(file) {
  updateTarget.value = { fileId: file.id, appId: currentAppId.value }
  updateInputRef.value.value = ''
  updateInputRef.value.click()
}

async function updateSelectedFile(event) {
  const file = event.target.files[0]
  const target = updateTarget.value
  if (!file || !target || updatingFileIds.value.has(target.fileId)) return
  updatingFileIds.value.add(target.fileId)
  try {
    await uploadFiles([file], target.fileId, target.appId)
  } finally {
    updatingFileIds.value.delete(target.fileId)
    event.target.value = ''
  }
}

async function fetchFiles({ append = false } = {}) {
  if (filesLoading.value) return
  filesLoading.value = true
  try {
    const params = { limit: 10 }
    if (currentAppId.value) params.app_id = currentAppId.value
    if (append && filesNextCursor.value) params.cursor = filesNextCursor.value
    const res = await axios.get(`${API}/files`, { params })
    const rows = res.data.files || []
    files.value = append ? files.value.concat(rows) : rows
    filesTotal.value = res.data.total || 0
    filesNextCursor.value = res.data.next_cursor || null
  }
  catch (err) { showToast('error', errorMessage(err)) }
  finally { filesLoading.value = false }
}

async function fetchNextFiles() {
  await fetchFiles({ append: true })
}

function onFilesScroll(event) {
  const wrap = filesTableRef.value?.scrollBarRef?.wrapRef
  if (!wrap) return
  const scrollTop = event?.scrollTop ?? wrap.scrollTop
  if (scrollTop + wrap.clientHeight >= wrap.scrollHeight - 24 && filesNextCursor.value) {
    fetchNextFiles()
  }
}

async function retryFile(file) {
  const targetAppId = currentAppId.value
  const key = file.id
  if (retryingFileIds.value.has(key)) return
  retryingFileIds.value.add(key)
  try {
    const response = await axios.post(`${API}/files`, { app_id: targetAppId, file_id: key })
    if (response.data.success) showToast('success', t('upload.indexSubmitted', { count: 1 }))
    else showToast('error', indexErrorMessage(response.data))
  } catch (err) {
    showToast('error', `${file.filename}: ${errorMessage(err)}`)
  } finally {
    retryingFileIds.value.delete(key)
    if (currentAppId.value === targetAppId) await fetchFiles()
  }
}

async function deleteFile(file) {
  if (!file?.id || deletingFileId.value) return
  deletingFileId.value = file.id
  try {
    const params = {}
    if (currentAppId.value) params.app_id = currentAppId.value
    await axios.delete(`${API}/files/${file.id}`, { params })
    showToast('success', t('upload.deletedFile', { name: file.filename }))
    await fetchFiles()
  } catch (err) {
    showToast('error', `${file.filename}: ${errorMessage(err)}`)
  } finally {
    deletingFileId.value = null
  }
}

onMounted(() => {
  fetchFiles()
})

watch(currentAppId, () => {
  files.value = []
  filesTotal.value = 0
  filesNextCursor.value = null
  fetchFiles()
})
</script>
