<template>
  <main class="monitor-view">
    <div v-if="!appId" class="trace-empty">{{ t('monitor.noAppSelected') }}</div>
    <template v-else>
    <div class="monitor-section">
      <div class="monitor-block trace-block">
        <div class="block-title job-title">
          <span>{{ t('monitor.indexJobs') }}</span>
          <div class="job-filters">
            <el-radio-group v-model="indexJobFilter" size="small">
              <el-radio-button v-for="filter in jobFilters" :key="filter" :value="filter">{{ t(`monitor.jobFilter.${filter}`) }}</el-radio-button>
            </el-radio-group>
            <el-button size="small" @click="fetchIndexJobs">{{ t('common.refresh') }}</el-button>
          </div>
        </div>
        <template v-if="filteredIndexJobs.length">
          <el-table ref="indexJobsTable" :data="filteredIndexJobs" max-height="320" @scroll="onIndexJobsScroll" v-loading="indexJobsLoading">
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
          <el-button v-if="indexJobsHasMore && !indexJobsLoading" class="docs-more" @click="fetchNextIndexJobs">{{ t('common.loadMore') }}</el-button>
        </template>
        <div v-else-if="indexJobsError" class="trace-empty error-text">{{ indexJobsError }}</div>
        <div v-else class="trace-empty">{{ t('monitor.noIndexJobs') }}</div>
      </div>
    </div>
    </template>
  </main>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'
import { shortTime, jobStatusClass } from '../utils/format'
import { useActiveAppStore } from '../stores/activeApp'

const API = '/api'
const { t } = useI18n()

const activeAppStore = useActiveAppStore()
const { appId } = storeToRefs(activeAppStore)

const indexJobs = ref([])
const indexJobsCursor = ref(null)
const indexJobsHasMore = ref(false)
const indexJobsLoading = ref(false)
const indexJobsError = ref('')
const indexJobFilter = ref('all')
const jobFilters = ['all', 'processing', 'finished', 'failed']
const indexJobsTable = ref(null)

const filteredIndexJobs = computed(() => {
  if (indexJobFilter.value === 'all') return indexJobs.value
  return indexJobs.value.filter(job => jobStatusClass(job.status) === indexJobFilter.value)
})

function jobStatusText(status) {
  return t(`monitor.jobStatus.${jobStatusClass(status)}`)
}

async function fetchIndexJobs() {
  indexJobs.value = []
  indexJobsCursor.value = null
  indexJobsHasMore.value = false
  indexJobsError.value = ''
  await fetchNextIndexJobs()
}

async function fetchNextIndexJobs() {
  if (indexJobsLoading.value) return
  indexJobsLoading.value = true
  try {
    const params = { limit: 50 }
    if (appId.value) params.app_id = appId.value
    if (indexJobsCursor.value) params.cursor = indexJobsCursor.value
    const res = await axios.get(`${API}/index/jobs`, { params })
    indexJobs.value = indexJobs.value.concat(res.data.jobs || [])
    indexJobsCursor.value = res.data.next_cursor || null
    indexJobsHasMore.value = Boolean(res.data.has_more)
    indexJobsError.value = ''
  }
  catch (err) {
    indexJobsError.value = err.response?.status === 503 ? t('monitor.indexQueueUnavailable') : (err.response?.data?.detail || err.message)
  }
  finally { indexJobsLoading.value = false }
}

function onIndexJobsScroll() {
  const wrap = indexJobsTable.value?.scrollBarRef?.wrapRef
  if (!wrap) return
  if (wrap.scrollTop + wrap.clientHeight >= wrap.scrollHeight - 24 && indexJobsHasMore.value) {
    fetchNextIndexJobs()
  }
}

onMounted(() => {
  fetchIndexJobs()
})
</script>
