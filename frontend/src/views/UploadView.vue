<template>
  <main class="upload-view">
    <div class="upload-card">
      <el-upload
        ref="uploadRef"
        drag
        multiple
        :auto-upload="false"
        :show-file-list="false"
        accept=".pdf,.txt,.md,.docx,.png,.jpg,.jpeg,.webp,.bmp"
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
        <h2>{{ t('upload.files') }}</h2>
        <span class="docs-count">{{ files.length }}</span>
      </div>
      <div v-if="files.length === 0 && !filesLoading" class="docs-empty">{{ t('upload.empty') }}</div>
      <template v-else>
        <el-table
          :data="files"
          style="width: 100%"
          max-height="360"
          v-loading="filesLoading"
        >
          <el-table-column label="file_id" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="chunk-id" :title="row.id">{{ row.id }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="filename" label="filename" min-width="220" show-overflow-tooltip />
          <el-table-column label="s3_url" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="chunk-id" :title="row.s3_url">{{ row.s3_url }}</span>
            </template>
          </el-table-column>
          <el-table-column label="created_at" min-width="160">
            <template #default="{ row }">{{ shortTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="size" label="size" width="100" />
          <el-table-column :label="t('common.actions')" width="100">
            <template #default="{ row }">
              <el-button type="danger" size="small" :disabled="deletingFileId === row.id" @click="deleteFile(row)">{{ deletingFileId === row.id ? t('common.deleting') : t('common.delete') }}</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="docs-pager">
          <el-button :disabled="!filesPrevCursor || filesLoading" @click="fetchFiles('prev')">&lt;</el-button>
          <el-button :disabled="!filesNextCursor || filesLoading" @click="fetchFiles('next')">&gt;</el-button>
        </div>
      </template>
    </div>
  </main>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'
import { useActiveAppStore } from '../stores/activeApp'
import { showToast } from '../utils/toast'
import { shortTime } from '../utils/format'

const API = '/api'
const { t } = useI18n()
const activeAppStore = useActiveAppStore()
const { appId } = storeToRefs(activeAppStore)

const selectedFiles = ref([])
const uploading = ref(false)
const files = ref([])
const filesPrevCursor = ref(null)
const filesNextCursor = ref(null)
const filesLoading = ref(false)
const deletingFileId = ref(null)
const uploadRef = ref(null)

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
  if (!activeAppStore.appId) {
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

async function uploadFiles(files) {
  let submitted = 0
  for (const file of files) {
    const form = new FormData()
    form.append('file', file)
    form.append('app_id', activeAppStore.appId)
    try {
      const uploadRes = await axios.post(`${API}/upload`, form)
      const presignRes = await axios.post(`${API}/presign`, { s3_url: uploadRes.data.s3_url })
      await axios.post(`${API}/index/jobs`, {
        app_id: activeAppStore.appId,
        file_id: uploadRes.data.file_id,
        presigned_url: presignRes.data.presigned_url,
        s3_url: uploadRes.data.s3_url,
      })
      submitted++
    } catch (err) {
      showToast('error', `${file.name}: ${err.response?.data?.detail || err.message}`)
    }
  }
  await fetchFiles()
  if (submitted > 0) {
    showToast('success', t('upload.indexSubmitted', { count: submitted }))
  }
  return submitted > 0
}

async function fetchFiles(direction) {
  if (filesLoading.value) return
  filesLoading.value = true
  try {
    const params = { limit: 10 }
    if (activeAppStore.appId) params.app_id = activeAppStore.appId
    if (direction === 'next' && filesNextCursor.value) params.cursor = filesNextCursor.value
    if (direction === 'prev' && filesPrevCursor.value) {
      params.cursor = filesPrevCursor.value
      params.direction = 'prev'
    }
    const res = await axios.get(`${API}/files`, { params })
    files.value = res.data.files || []
    filesPrevCursor.value = res.data.prev_cursor || null
    filesNextCursor.value = res.data.next_cursor || null
  }
  catch (err) { console.error(err) }
  finally { filesLoading.value = false }
}

async function deleteFile(file) {
  if (!file?.id || deletingFileId.value) return
  deletingFileId.value = file.id
  try {
    const params = {}
    if (activeAppStore.appId) params.app_id = activeAppStore.appId
    await axios.delete(`${API}/files/${file.id}`, { params })
    showToast('success', t('upload.deletedFile', { name: file.filename }))
    await fetchFiles()
  } catch (err) {
    showToast('error', `${file.filename}: ${err.response?.data?.detail || err.message}`)
  } finally {
    deletingFileId.value = null
  }
}

onMounted(fetchFiles)
</script>
