<template>
  <main class="monitor-view">
    <div v-if="!appId" class="trace-empty">{{ t('monitor.noAppSelected') }}</div>
    <template v-else>
    <div class="monitor-section">
      <div class="monitor-block trace-block">
        <div class="block-title job-title">
          <span>{{ t('monitor.indexJobs') }}</span>
          <span class="trace-note">{{ t('monitor.indexJobsLimitNote', { count: INDEX_JOB_LIMIT }) }}</span>
        </div>
        <template v-if="indexJobs.length">
          <el-table :data="indexJobs" max-height="320" v-loading="indexJobsLoading">
            <el-table-column :label="t('monitor.jobColumns.status')" min-width="82">
              <template #default="{ row }">
                <span :class="['job-status', jobStatusClass(row.status)]">{{ jobStatusText(row.status) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="job_id" :label="t('monitor.jobColumns.jobId')" min-width="170" show-overflow-tooltip />
            <el-table-column :label="t('monitor.jobColumns.filename')" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">
                <span>{{ row.filename || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="file_id" :label="t('monitor.jobColumns.fileId')" min-width="170" show-overflow-tooltip />
            <el-table-column prop="chunk_count" :label="t('monitor.jobColumns.chunks')" width="58" />
            <el-table-column :label="t('monitor.jobColumns.error')" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="job-error">{{ row.error || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('monitor.jobColumns.created')" min-width="160">
              <template #default="{ row }">{{ shortTime(row.created_at || row.enqueued_at) }}</template>
            </el-table-column>
            <el-table-column :label="t('monitor.jobColumns.ended')" min-width="160">
              <template #default="{ row }">{{ shortTime(row.ended_at) }}</template>
            </el-table-column>
          </el-table>
        </template>
        <div v-else-if="indexJobsError" class="trace-empty error-text">{{ indexJobsError }}</div>
        <div v-else class="trace-empty">{{ t('monitor.noIndexJobs') }}</div>
      </div>
    </div>
    </template>
  </main>
</template>

<script setup>
import { ref, onMounted, watch, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'
import { shortTime, jobStatusClass } from '../utils/format'
import { useActiveAppStore } from '../stores/activeApp'

const API = '/api'
const INDEX_JOB_LIMIT = 200
const { t } = useI18n()

const activeAppStore = useActiveAppStore()
const { appId } = storeToRefs(activeAppStore)

const indexJobs = ref([])
const indexJobsLoading = ref(false)
const indexJobsError = ref('')
let jobStreamController = null

function jobStatusText(status) {
  return t(`monitor.jobStatus.${jobStatusClass(status)}`)
}

async function fetchIndexJobs() {
  indexJobsLoading.value = true
  try {
    const params = { limit: INDEX_JOB_LIMIT }
    if (appId.value) params.app_id = appId.value
    const res = await axios.get(`${API}/index/jobs`, { params })
    indexJobs.value = res.data.jobs || []
    indexJobsError.value = ''
  }
  catch (err) {
    indexJobsError.value = err.response?.status === 503 ? t('monitor.indexQueueUnavailable') : (err.response?.data?.detail || err.message)
  }
  finally { indexJobsLoading.value = false }
}

async function startJobStream() {
  stopJobStream()
  if (!appId.value) return
  jobStreamController = new AbortController()
  try {
    const token = localStorage.getItem('rag_token') || ''
    const response = await fetch(`${API}/index/jobs/stream?app_id=${appId.value}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: jobStreamController.signal,
    })
    if (!response.ok || !response.body) return
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) handleJobEvent(part)
    }
  } catch (err) {
    if (err.name !== 'AbortError') console.error(err)
  }
}

function stopJobStream() {
  if (jobStreamController) {
    jobStreamController.abort()
    jobStreamController = null
  }
}

function handleJobEvent(eventText) {
  const line = eventText.split('\n').find(item => item.startsWith('data: '))
  if (!line) return
  let row
  try {
    row = JSON.parse(line.slice(6))
  } catch (err) {
    return
  }
  const existing = indexJobs.value.find(job => job.job_id === row.job_id)
  if (existing) {
    existing.status = row.status
  } else {
    indexJobs.value.unshift({ job_id: row.job_id, status: row.status, filename: row.filename })
    if (indexJobs.value.length > INDEX_JOB_LIMIT) indexJobs.value.pop()
  }
}

onMounted(() => {
  fetchIndexJobs()
  startJobStream()
})

onUnmounted(() => {
  stopJobStream()
})

watch(appId, () => {
  fetchIndexJobs()
  stopJobStream()
  startJobStream()
})
</script>
