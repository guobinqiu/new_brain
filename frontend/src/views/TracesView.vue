<template>
  <main class="monitor-view">
    <div v-if="!currentAppId" class="trace-empty">{{ t('monitor.noAppSelected') }}</div>
    <template v-else>
    <div class="monitor-section">
      <div class="monitor-block trace-block">
        <div class="block-title job-title">
          <span>{{ t('monitor.traces') }}</span>
          <el-date-picker
            v-model="timeRange"
            type="datetimerange"
            value-format="x"
            size="small"
            class="trace-time-range"
            :start-placeholder="t('common.startTime')"
            :end-placeholder="t('common.endTime')"
          />
          <el-button size="small" type="primary" :loading="tracesLoading" @click="loadTraces">{{ t('common.search') }}</el-button>
        </div>
        <template v-if="traces.length">
          <el-table ref="tracesTableRef" :data="traces" max-height="320" v-loading="tracesLoading" @scroll="onTracesScroll">
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
import { computed, ref, watch, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { ms, shortTime } from '../utils/format'
import { useActiveAppStore } from '../stores/activeApp'
import axios from '../utils/api'

const TRACE_LIMIT = 500
const { t } = useI18n()

const activeAppStore = useActiveAppStore()
const { appId } = storeToRefs(activeAppStore)
const route = useRoute()

const traces = ref([])
const tracesLoading = ref(false)
const tracesHasMore = ref(false)
const tracesNextStart = ref(null)
const tracesTableRef = ref(null)
const timeRange = ref(defaultRange())
const currentAppId = computed(() => route.params.app_id || appId.value)

function defaultRange() {
  const end = Date.now()
  return [end - 24 * 60 * 60 * 1000, end]
}

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

async function loadTraces() {
  traces.value = []
  tracesHasMore.value = false
  tracesNextStart.value = null
  await fetchNextTraces()
}

async function fetchNextTraces() {
  if (!currentAppId.value) return
  if (tracesLoading.value) return
  tracesLoading.value = true
  try {
    const params = {
      app_id: currentAppId.value,
      limit: TRACE_LIMIT,
    }
    if (timeRange.value?.length === 2) {
      params.start = timeRange.value[0]
      params.end = timeRange.value[1]
    }
    if (tracesNextStart.value != null) params.start = tracesNextStart.value
    const res = await axios.get('/api/traces', {
      params,
    })
    traces.value = traces.value.concat(res.data?.traces || [])
    tracesHasMore.value = Boolean(res.data?.has_more)
    tracesNextStart.value = res.data?.next_start || null
  } finally {
    tracesLoading.value = false
  }
}

function onTracesScroll(event) {
  const wrap = tracesTableRef.value?.scrollBarRef?.wrapRef
  if (!wrap || tracesLoading.value || !tracesHasMore.value) return
  const scrollTop = event?.scrollTop ?? wrap.scrollTop
  if (scrollTop + wrap.clientHeight >= wrap.scrollHeight - 24) {
    fetchNextTraces()
  }
}

onMounted(() => {
  loadTraces()
})

watch(currentAppId, () => {
  loadTraces()
})
</script>
