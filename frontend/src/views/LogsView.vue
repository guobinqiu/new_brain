<template>
  <main class="logs-view">
    <div class="monitor-section">
      <div class="monitor-head">
        <div>
          <h2>{{ t('logs.title') }}</h2>
          <p>{{ t('logs.desc') }}</p>
        </div>
        <div class="log-filters">
          <el-select v-model="nodeId" size="small" class="log-filter" @change="restartLogs">
            <el-option :label="t('cluster.allNodes')" value="" />
            <el-option v-for="node in nodes" :key="node" :label="node" :value="node" />
          </el-select>
          <el-select v-model="container" size="small" class="log-filter" filterable @change="restartLogs">
            <el-option v-for="item in containers" :key="item" :label="item" :value="item" />
          </el-select>
        </div>
      </div>
      <div class="monitor-block trace-block">
        <pre v-if="logs.length" ref="logsBox" class="logs-box">{{ logs.map(formatLogLine).join('\n') }}</pre>
        <div v-else class="trace-empty">{{ t('logs.empty') }}</div>
      </div>
    </div>
  </main>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'
import { fetchLabelValues, logs, logsBox, formatLogLine, startLogsTail, stopLogsTail } from '../utils/loki'

const { t } = useI18n()
const nodeId = ref('')
const container = ref('rag-backend')
const nodes = ref([])
const containers = ref([])

async function loadFilters() {
  const [monitorRes, containerValues] = await Promise.all([
    axios.get('/api/nodes/monitor'),
    fetchLabelValues('container'),
  ])
  nodes.value = (monitorRes.data?.nodes || []).map(node => node.node_id)
  containers.value = containerValues.length ? containerValues : ['rag-backend']
  if (!containers.value.includes(container.value)) container.value = containers.value[0]
}

function restartLogs() {
  startLogsTail({ nodeId: nodeId.value, container: container.value })
}

onMounted(async () => {
  await loadFilters()
  restartLogs()
})
onUnmounted(stopLogsTail)
</script>
