<template>
  <main class="monitor-view">
    <!-- Runtime Monitor -->
    <div class="monitor-section">
      <div class="monitor-head">
        <div>
          <h2>{{ t('monitor.title') }}</h2>
          <p>{{ monitorState?.profile?.config_name || '-' }} · {{ monitorState?.profile?.store?.type || '-' }}</p>
        </div>
      </div>
      <div class="monitor-grid">
        <div class="monitor-block">
          <div class="block-title component-title">
            <span>{{ t('monitor.components') }}</span>
            <span class="status-legend">
              <span><i class="status-dot ready"></i>{{ t('status.ready') }}</span>
              <span><i class="status-dot loading"></i>{{ t('status.loading') }}</span>
              <span><i class="status-dot disabled"></i>{{ t('status.disabled') }}</span>
              <span><i class="status-dot error"></i>{{ t('status.error') }}</span>
            </span>
          </div>
          <div class="component-list">
            <div v-for="item in components" :key="item.name" class="component-row">
              <span :class="['status-dot', item.status]"></span>
              <span class="component-name">{{ item.name }}</span>
              <strong>{{ componentModelText(item) }}</strong>
            </div>
          </div>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'

const API = '/api'
const { t } = useI18n()

const monitorState = ref(null)
let monitorPollTimer = null

const components = computed(() => monitorState.value?.components || [])

function componentModelText(item) {
  if (!item.model) return 'N/A'
  return item.mode ? `${item.model}（${item.mode}）` : item.model
}

async function fetchMonitor() {
  try {
    const res = await axios.get(`${API}/admin/monitor`)
    monitorState.value = res.data
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
