<template>
  <main class="logs-view">
    <div class="monitor-section">
      <div class="monitor-head">
        <div>
          <h2>{{ t('logs.title') }}</h2>
          <p>{{ t('logs.desc') }}</p>
        </div>
        <div class="log-filters">
          <el-date-picker
            v-model="timeRange"
            type="datetimerange"
            value-format="x"
            size="small"
            class="log-time-range"
            :start-placeholder="t('common.startTime')"
            :end-placeholder="t('common.endTime')"
          />
          <el-select v-model="nodeId" size="small" class="log-filter">
            <el-option :label="t('cluster.allNodes')" value="" />
            <el-option v-for="node in nodes" :key="node" :label="node" :value="node" />
          </el-select>
          <el-select v-model="container" size="small" class="log-filter" filterable>
            <el-option :label="t('logs.allContainers')" value="" />
            <el-option v-for="item in containers" :key="item" :label="item" :value="item" />
          </el-select>
          <el-button size="small" type="primary" :loading="loading" @click="loadLogs">{{ t('common.search') }}</el-button>
        </div>
      </div>
      <div class="monitor-block trace-block">
        <pre v-if="logs.length" ref="logsBoxRef" class="logs-box" @scroll="onLogsScroll">{{ logs.map(formatLogLine).join('\n') }}</pre>
        <div v-else class="trace-empty">{{ t('logs.empty') }}</div>
      </div>
    </div>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { errorMessage, showToast } from '../utils/toast'
import { fetchLabelValues, fetchLogs, formatLogLine } from '../utils/loki'

const { t } = useI18n()
const nodeId = ref('')
const container = ref('')
const nodes = ref([])
const containers = ref([])
const logs = ref([])
const loading = ref(false)
const logsBoxRef = ref(null)
const logsHasMore = ref(false)
const logsNextStart = ref(null)
const timeRange = ref(defaultRange())

function defaultRange() {
  const end = Date.now()
  return [end - 15 * 60 * 1000, end]
}

async function loadFilters() {
  const [nodeValues, containerValues] = await Promise.all([
    fetchLabelValues('node_id'),
    fetchLabelValues('container'),
  ])
  nodes.value = nodeValues
  containers.value = containerValues
  if (container.value && !containers.value.includes(container.value)) container.value = ''
}

async function loadLogs() {
  logs.value = []
  logsHasMore.value = false
  logsNextStart.value = null
  await fetchNextLogs()
}

async function fetchNextLogs() {
  if (loading.value) return
  loading.value = true
  try {
    const res = await fetchLogs({
      nodeId: nodeId.value,
      container: container.value,
      range: timeRange.value,
      start: logsNextStart.value,
    })
    logs.value = logs.value.concat(res.logs || [])
    logsHasMore.value = Boolean(res.has_more)
    logsNextStart.value = res.next_start || null
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    loading.value = false
  }
}

function onLogsScroll(event) {
  const target = event.target
  if (!target || loading.value || !logsHasMore.value) return
  if (target.scrollTop + target.clientHeight >= target.scrollHeight - 24) {
    fetchNextLogs()
  }
}

onMounted(async () => {
  try {
    await loadFilters()
  } catch (err) {
    showToast('error', errorMessage(err))
  }
  await loadLogs()
})
</script>
