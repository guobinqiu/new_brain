<template>
  <main class="config-view">
    <div class="monitor-section">
      <div class="monitor-head">
        <div>
          <h2>{{ t('config.title') }}</h2>
          <p>{{ t('cluster.configDesc') }}</p>
        </div>
        <el-button size="small" @click="fetchConfig">{{ t('common.refresh') }}</el-button>
      </div>
      <div class="node-grid">
        <div v-for="node in nodes" :key="node.node_id" class="monitor-block">
          <div class="node-head">
            <div>
              <div class="block-title">{{ node.node_id }}</div>
              <p>{{ node.base_url }}</p>
            </div>
            <el-tag :type="node.status === 'ok' ? driftTagType(node) : 'danger'" size="small">
              {{ nodeStatusText(node) }}
            </el-tag>
          </div>
          <div v-if="node.status === 'ok'" class="config-grid">
            <div class="kv-list">
              <div><span>{{ t('config.searchDefaults') }}</span><strong>{{ node.data?.config_name || '-' }}</strong></div>
              <div><span>mode</span><strong>{{ node.data?.default_mode || '-' }}</strong></div>
              <div><span>top_k</span><strong>{{ node.data?.top_k ?? '-' }}</strong></div>
              <div><span>fetch_k</span><strong>{{ node.data?.fetch_k ?? '-' }}</strong></div>
              <div><span>dense_weight</span><strong>{{ node.data?.dense_weight ?? '-' }}</strong></div>
              <div><span>sparse_weight</span><strong>{{ node.data?.sparse_weight ?? '-' }}</strong></div>
              <div><span>rrf_k</span><strong>{{ node.data?.rrf_k ?? '-' }}</strong></div>
            </div>
            <div class="kv-list">
              <div><span>{{ t('config.components') }}</span><strong></strong></div>
              <div><span>dense</span><strong>{{ configComponentModel(node.data?.dense) }}</strong></div>
              <div><span>sparse</span><strong>{{ configComponentModel(node.data?.sparse) }}</strong></div>
              <div><span>rerank</span><strong>{{ configComponentModel(node.data?.rerank) }}</strong></div>
              <div><span>ocr</span><strong>{{ configComponentModel(node.data?.ocr) }}</strong></div>
            </div>
            <div class="kv-list">
              <div><span>{{ t('config.storage') }}</span><strong>{{ node.data?.store?.type || '-' }}</strong></div>
              <div><span>{{ t('database.location') }}</span><strong>{{ configStoreLocation(node.data) }}</strong></div>
            </div>
          </div>
          <div v-else class="trace-empty">{{ node.error }}</div>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'

const { t } = useI18n()

const nodes = ref([])

const baselineConfig = computed(() => {
  const node = nodes.value.find(item => item.status === 'ok')
  return node ? comparableConfig(node.data) : null
})

function configStoreLocation(config) {
  const store = config?.store
  return store?.url || store?.uri || store?.persist_dir || '-'
}

function configComponentModel(item) {
  if (!item || item.enable === false) return 'disabled'
  return item.model_name || item.name || item.type || '-'
}

function nodeStatusText(node) {
  if (node.status !== 'ok') return t('cluster.unreachable')
  return hasConfigDrift(node) ? t('cluster.configDrift') : 'ok'
}

function driftTagType(node) {
  return hasConfigDrift(node) ? 'warning' : 'success'
}

function hasConfigDrift(node) {
  return Boolean(baselineConfig.value && JSON.stringify(comparableConfig(node.data)) !== JSON.stringify(baselineConfig.value))
}

function comparableConfig(data) {
  const { node_id, ...rest } = data || {}
  return rest
}

async function fetchConfig() {
  try {
    const res = await axios.get('/api/nodes/config')
    nodes.value = res.data?.nodes || []
  } catch (err) { console.error(err) }
}

onMounted(fetchConfig)
</script>
