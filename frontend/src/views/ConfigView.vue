<template>
  <main class="config-view">
    <div class="monitor-section">
      <div class="monitor-head">
        <div>
          <h2>{{ t('config.title') }}</h2>
          <p>{{ configView?.config_name || '-' }}</p>
        </div>
      </div>
      <div class="config-grid">
        <div class="monitor-block">
          <div class="block-title">{{ t('config.searchDefaults') }}</div>
          <div class="kv-list">
            <div><span>mode</span><strong>{{ configView?.default_mode || '-' }}</strong></div>
            <div><span>top_k</span><strong>{{ configView?.top_k ?? '-' }}</strong></div>
            <div><span>fetch_k</span><strong>{{ configView?.fetch_k ?? '-' }}</strong></div>
            <div><span>dense_weight</span><strong>{{ configView?.dense_weight ?? '-' }}</strong></div>
            <div><span>sparse_weight</span><strong>{{ configView?.sparse_weight ?? '-' }}</strong></div>
            <div><span>rrf_k</span><strong>{{ configView?.rrf_k ?? '-' }}</strong></div>
          </div>
        </div>
        <div class="monitor-block">
          <div class="block-title">{{ t('config.components') }}</div>
          <div class="kv-list">
            <div><span>dense</span><strong>{{ configComponentModel(configView?.dense) }}</strong></div>
            <div><span>sparse</span><strong>{{ configComponentModel(configView?.sparse) }}</strong></div>
            <div><span>rerank</span><strong>{{ configComponentModel(configView?.rerank) }}</strong></div>
            <div><span>ocr</span><strong>{{ configComponentModel(configView?.ocr) }}</strong></div>
          </div>
        </div>
        <div class="monitor-block">
          <div class="block-title">{{ t('config.storage') }}</div>
          <div class="kv-list">
            <div><span>store</span><strong>{{ configView?.store?.type || '-' }}</strong></div>
            <div><span>{{ t('database.location') }}</span><strong>{{ configStoreLocation }}</strong></div>
          </div>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'

const API = '/api'
const { t } = useI18n()

const configView = ref(null)

const configStoreLocation = computed(() => {
  const store = configView.value?.store
  return store?.url || store?.uri || store?.persist_dir || '-'
})

function configComponentModel(item) {
  if (!item || item.enable === false) return 'disabled'
  return item.model_name || item.name || item.type || '-'
}

async function fetchConfig() {
  try {
    const res = await axios.get(`${API}/config`)
    configView.value = res.data
  } catch (err) { console.error(err) }
}

onMounted(fetchConfig)
</script>
