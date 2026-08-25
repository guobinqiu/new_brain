<template>
  <main class="monitor-view">
    <!-- Runtime Monitor -->
    <div class="monitor-section">
      <div class="monitor-head">
        <div>
          <h2>{{ t('monitor.title') }}</h2>
          <p>{{ t('cluster.desc') }}</p>
        </div>
      </div>
      <div class="node-grid">
        <div v-for="node in nodes" :key="node.node_id" class="monitor-block">
          <div class="node-head">
            <div>
              <div class="block-title">{{ node.node_id }}</div>
              <p>{{ node.base_url }}</p>
            </div>
          </div>
          <template v-if="node.status === 'ok'">
            <div class="node-summary">{{ node.data?.profile?.config_name || '-' }} · {{ node.data?.profile?.store?.type || '-' }}</div>
            <div class="component-title">
              <span>{{ t('monitor.components') }}</span>
              <span class="status-legend">
                <span><i class="status-dot ready"></i>{{ t('status.ready') }}</span>
                <span><i class="status-dot loading"></i>{{ t('status.loading') }}</span>
                <span><i class="status-dot disabled"></i>{{ t('status.disabled') }}</span>
                <span><i class="status-dot error"></i>{{ t('status.error') }}</span>
              </span>
            </div>
            <div class="component-list">
              <div v-for="item in node.data?.components || []" :key="item.name" class="component-row">
                <span :class="['status-dot', item.status]"></span>
                <span class="component-name">{{ item.name }}</span>
                <strong>{{ componentModelText(item) }}</strong>
              </div>
            </div>
          </template>
          <div v-else class="trace-empty">{{ node.error }}</div>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'

const { t } = useI18n()

const nodes = ref([])
let monitorPollTimer = null

function componentModelText(item) {
  if (!item.model) return 'N/A'
  return item.mode ? `${item.model}（${item.mode}）` : item.model
}

async function fetchMonitor() {
  try {
    const res = await axios.get('/api/nodes/monitor')
    nodes.value = res.data?.nodes || []
  } catch (err) { console.error(err) }
}

async function pollMonitor() {
  await fetchMonitor()
}

function startMonitorPolling() {
  stopMonitorPolling()
  pollMonitor()
  monitorPollTimer = window.setInterval(pollMonitor, 1000)
}

function stopMonitorPolling() {
  if (monitorPollTimer) {
    window.clearInterval(monitorPollTimer)
    monitorPollTimer = null
  }
}

onMounted(() => {
  startMonitorPolling()
})

onUnmounted(() => {
  stopMonitorPolling()
})
</script>
