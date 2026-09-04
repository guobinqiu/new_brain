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
          </div>
          <div v-if="node.status === 'ok'" class="config-grid">
            <div class="config-panel">
              <div class="config-panel-title">{{ t('config.searchDefaults') }}</div>
              <div class="kv-list">
                <div><span>profile</span><strong :title="node.data?.config_name || '-'">{{ node.data?.config_name || '-' }}</strong></div>
                <div><span>mode</span><strong>{{ node.data?.default_mode || '-' }}</strong></div>
                <div><span>top_k</span><strong>{{ node.data?.top_k ?? '-' }}</strong></div>
                <div><span>fetch_k</span><strong>{{ node.data?.fetch_k ?? '-' }}</strong></div>
                <div><span>dense_weight</span><strong>{{ node.data?.dense_weight ?? '-' }}</strong></div>
                <div><span>sparse_weight</span><strong>{{ node.data?.sparse_weight ?? '-' }}</strong></div>
                <div><span>rrf_k</span><strong>{{ node.data?.rrf_k ?? '-' }}</strong></div>
              </div>
            </div>
            <div class="config-panel">
              <div class="config-panel-title">{{ t('config.components') }}</div>
              <div class="kv-list">
                <div><span>dense</span><strong :title="configComponentModel(node.data?.dense)">{{ configComponentModel(node.data?.dense) }}</strong></div>
                <div><span>sparse</span><strong :title="configComponentModel(node.data?.sparse)">{{ configComponentModel(node.data?.sparse) }}</strong></div>
                <div><span>rerank</span><strong :title="configComponentModel(node.data?.rerank)">{{ configComponentModel(node.data?.rerank) }}</strong></div>
                <div><span>ocr</span><strong :title="configComponentModel(node.data?.ocr)">{{ configComponentModel(node.data?.ocr) }}</strong></div>
              </div>
            </div>
            <div class="config-panel">
              <div class="config-panel-title">{{ t('config.parser') }}</div>
              <div class="kv-list">
                <div><span>type</span><strong>{{ node.data?.parser?.enabled || '-' }}</strong></div>
                <div><span>text.chunk_size</span><strong>{{ activeParserConfig(node.data?.parser)?.text?.chunk_size ?? '-' }}</strong></div>
                <div><span>text.chunk_overlap</span><strong>{{ activeParserConfig(node.data?.parser)?.text?.chunk_overlap ?? '-' }}</strong></div>
                <div><span>table.header_backward_chars</span><strong>{{ activeParserConfig(node.data?.parser)?.table?.header_backward_chars ?? '-' }}</strong></div>
                <div><span>table.footer_forward_chars</span><strong>{{ activeParserConfig(node.data?.parser)?.table?.footer_forward_chars ?? '-' }}</strong></div>
              </div>
            </div>
            <div class="config-panel">
              <div class="config-panel-title">{{ t('config.storage') }}</div>
              <div class="kv-list">
                <div><span>store</span><strong>{{ node.data?.store?.type || '-' }}</strong></div>
                <div><span>{{ t('database.location') }}</span><strong :title="configStoreLocation(node.data)">{{ configStoreLocation(node.data) }}</strong></div>
              </div>
            </div>
          </div>
          <div v-else class="trace-empty">{{ node.error }}</div>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'

const { t } = useI18n()

const nodes = ref([])

function configStoreLocation(config) {
  const store = config?.store
  return store?.url || store?.uri || store?.persist_dir || '-'
}

function configComponentModel(item) {
  if (!item || item.enable === false) return 'disabled'
  return item.model_name || item.name || item.type || item.backend || '-'
}

function activeParserConfig(parser) {
  if (!parser?.enabled) return null
  return parser[parser.enabled]
}

async function fetchConfig() {
  try {
    const res = await axios.get('/api/open/rag/nodes/config')
    nodes.value = res.data?.nodes || []
  } catch (err) { console.error(err) }
}

onMounted(fetchConfig)
</script>
