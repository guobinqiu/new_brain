<template>
  <main class="monitor-view">
    <div v-if="!currentAppId" class="trace-empty">{{ t('monitor.noAppSelected') }}</div>
    <template v-else>
    <div class="monitor-section">
      <div class="monitor-block trace-block">
        <div class="block-title job-title">
          <span>{{ t('monitor.traces') }}</span>
          <span class="trace-note">{{ t('trace.limitNote', { count: TRACE_LIMIT }) }}</span>
        </div>
        <template v-if="traces.length">
          <el-table :data="traces" max-height="320" v-loading="tracesLoading">
            <el-table-column :label="t('trace.columns.time')" min-width="150">
              <template #default="{ row }">{{ shortTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column :label="t('trace.columns.query')" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="trace-query">{{ row.query }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('trace.columns.mode')" width="90">
              <template #default="{ row }">{{ traceModeText(row.mode) }}</template>
            </el-table-column>
            <el-table-column prop="top_k" :label="t('trace.columns.topK')" width="46" />
            <el-table-column :label="t('trace.columns.elapsed')" width="72">
              <template #default="{ row }"><strong>{{ ms(row.elapsed_ms) }}</strong></template>
            </el-table-column>
            <el-table-column :label="t('trace.columns.prepare')" width="72">
              <template #default="{ row }">{{ stageMs(row, 'prepare_plan') }}</template>
            </el-table-column>
            <el-table-column :label="t('trace.columns.dense')" width="72">
              <template #default="{ row }">{{ stageMs(row, 'dense') }}</template>
            </el-table-column>
            <el-table-column :label="t('trace.columns.sparse')" width="72">
              <template #default="{ row }">{{ stageMs(row, 'sparse') }}</template>
            </el-table-column>
            <el-table-column :label="t('trace.columns.fusion')" width="72">
              <template #default="{ row }">{{ stageMs(row, 'fusion') }}</template>
            </el-table-column>
            <el-table-column :label="t('trace.columns.dedupe')" width="72">
              <template #default="{ row }">{{ stageMs(row, 'dedupe') }}</template>
            </el-table-column>
            <el-table-column :label="t('trace.columns.rerank')" width="72">
              <template #default="{ row }">{{ stageMs(row, 'rerank') }}</template>
            </el-table-column>
            <el-table-column :label="t('trace.columns.format')" width="72">
              <template #default="{ row }">{{ stageMs(row, 'format_response') }}</template>
            </el-table-column>
          </el-table>
        </template>
        <div v-else class="trace-empty">{{ t('monitor.noTraces') }}</div>
      </div>
    </div>
    </template>
  </main>
</template>

<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import axios from '../utils/api'
import { ms, shortTime } from '../utils/format'
import { useActiveAppStore } from '../stores/activeApp'
import { useAuthStore } from '../stores/auth'

const TRACE_LIMIT = 200
const { t } = useI18n()

const activeAppStore = useActiveAppStore()
const { appId } = storeToRefs(activeAppStore)
const authStore = useAuthStore()
const route = useRoute()

const traces = ref([])
const tracesLoading = ref(false)
let traceSource = null
const currentAppId = computed(() => route.params.app_id || appId.value)

function stageMs(trace, name) {
  const stage = (trace.stages || []).find(item => item.name === name)
  return stage ? ms(stage.elapsed_ms) : '-'
}

function traceModeText(mode) {
  if (!mode) return '-'
  const key = `trace.modeValues.${mode}`
  const text = t(key)
  return text === key ? mode : text
}

async function fetchTraces() {
  const res = await axios.get('/api/traces', {
    params: {
      app_id: currentAppId.value,
      limit: TRACE_LIMIT,
    },
  })
  traces.value = res.data.traces || []
}

async function startTraces() {
  stopTraces()
  traces.value = []
  if (!currentAppId.value) return
  tracesLoading.value = true
  try {
    await fetchTraces()
  } finally {
    tracesLoading.value = false
  }
  const params = new URLSearchParams()
  params.set('token', authStore.authToken)
  params.set('app_id', currentAppId.value)
  params.set('limit', String(TRACE_LIMIT))
  traceSource = new EventSource(`/api/traces/stream?${params.toString()}`)
  traceSource.onmessage = event => {
    const next = JSON.parse(event.data)
    if (next.length || !traces.value.length) traces.value = next
    tracesLoading.value = false
  }
  traceSource.onerror = () => {
    tracesLoading.value = false
  }
}

function stopTraces() {
  if (traceSource) {
    traceSource.close()
    traceSource = null
  }
}

onMounted(() => {
  startTraces()
})

onUnmounted(() => {
  stopTraces()
})

watch(currentAppId, () => {
  startTraces()
})
</script>
