<template>
  <main class="debug-view">
    <div class="page-head">
      <div>
        <h2>{{ t('debug.title') }}</h2>
        <p>{{ t('debug.desc') }}</p>
      </div>
    </div>

    <section class="debug-card">
      <div class="debug-form">
        <el-input
          v-model.trim="debugQueryText"
          type="textarea"
          :rows="4"
          :placeholder="t('debug.placeholder')"
        />
        <div class="debug-actions">
          <div class="debug-topk">
            <span>{{ t('debug.topK') }}</span>
            <el-input-number v-model="debugTopK" :min="1" :max="100" size="small" controls-position="right" />
          </div>
          <el-button :disabled="!canDense" :loading="debugLoading === 'dense-encode'" @click="debugEncode">{{ t('debug.encodeDense') }}</el-button>
          <el-button type="primary" :disabled="!canDense" :loading="debugLoading === 'dense-search'" @click="debugSearch">{{ t('debug.queryDense') }}</el-button>
        </div>
      </div>

      <div v-if="debugVectorBody" class="debug-vector">
        <div class="vector-meta">{{ debugVectorMeta }}</div>
        <pre class="vector-body">{{ debugVectorBody }}</pre>
      </div>

      <el-table v-if="debugResults.length" :data="debugResults" class="debug-results" max-height="420">
        <el-table-column :label="t('database.score')" min-width="100">
          <template #default="{ row }">{{ formatScore(row.score) }}</template>
        </el-table-column>
        <el-table-column prop="id" :label="t('database.chunkId')" min-width="140" show-overflow-tooltip />
        <el-table-column prop="file_id" :label="t('database.fileId')" min-width="170" show-overflow-tooltip />
        <el-table-column prop="filename" :label="t('database.filename')" min-width="120" show-overflow-tooltip />
        <el-table-column prop="chunk_index" :label="t('database.chunkIndex')" min-width="120" />
        <el-table-column :label="t('database.content')" min-width="320">
          <template #default="{ row }">
            <div class="copy-cell">
              <el-tooltip placement="top" popper-class="chunk-content-tooltip">
                <template #content>
                  <div class="chunk-content-tooltip-body">{{ row.content }}</div>
                </template>
                <span class="chunk-content">{{ row.content }}</span>
              </el-tooltip>
              <el-button :icon="CopyDocument" circle size="small" @click.stop="copyText(row.content)" />
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" min-width="150" fixed="right">
          <template #default="{ row }">
            <div class="vector-actions">
              <el-button v-if="denseVectorAvailable" size="small" @click.stop="showDenseVector(row)">{{ t('database.denseVector') }}</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>
    <el-dialog v-model="vectorDialogVisible" :title="vectorDialogTitle" width="720px">
      <div v-if="vectorDialogMeta" class="vector-meta">{{ vectorDialogMeta }}</div>
      <pre class="vector-body">{{ vectorDialogBody }}</pre>
    </el-dialog>
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { CopyDocument } from '@element-plus/icons-vue'
import axios from '../utils/api'
import { copyText } from '../utils/format'
import { errorMessage, showToast } from '../utils/toast'

const API = '/api/rag'
const { t } = useI18n()
const route = useRoute()
const currentAppId = computed(() => route.params.app_id)

const capabilities = ref({})
const debugQueryText = ref('')
const debugTopK = ref(20)
const debugLoading = ref('')
const debugVectorBody = ref('')
const debugVectorMeta = ref('')
const debugResults = ref([])
const vectorDialogVisible = ref(false)
const vectorDialogTitle = ref('')
const vectorDialogBody = ref('')
const vectorDialogMeta = ref('')

const denseVectorAvailable = computed(() => capabilities.value.dense_vector === true)
const canDense = computed(() => currentAppId.value && debugQueryText.value && denseVectorAvailable.value && !debugLoading.value)

async function fetchConfig() {
  try {
    const res = await axios.get(`${API}/config`)
    capabilities.value = res.data?.capabilities || {}
  } catch (err) {
    capabilities.value = {}
    showToast('error', errorMessage(err))
  }
}

async function debugEncode() {
  if (!canDense.value) return
  debugLoading.value = 'dense-encode'
  debugResults.value = []
  try {
    const res = await axios.post(`${API}/apps/${currentAppId.value}/debug/dense-encode`, { query: debugQueryText.value })
    setDebugVector(res.data)
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    debugLoading.value = ''
  }
}

async function debugSearch() {
  if (!canDense.value) return
  debugLoading.value = 'dense-search'
  try {
    const res = await axios.post(`${API}/apps/${currentAppId.value}/debug/dense-search`, { query: debugQueryText.value, top_k: debugTopK.value })
    setDebugVector(res.data)
    debugResults.value = res.data?.results || []
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    debugLoading.value = ''
  }
}

function setDebugVector(data) {
  const vector = data?.query_vector || {}
  debugVectorMeta.value = t('database.vectorDimension', { count: Array.isArray(vector) ? vector.length : 0 })
  debugVectorBody.value = JSON.stringify(vector, null, 2)
}

async function showDenseVector(row) {
  if (!currentAppId.value || !row?.id) return
  try {
    const res = await axios.get(`${API}/apps/${currentAppId.value}/chunks/${row.id}/dense-vector`)
    vectorDialogTitle.value = t('database.denseVectorTitle')
    vectorDialogMeta.value = vectorMeta(res.data.vector)
    vectorDialogBody.value = JSON.stringify(res.data.vector, null, 2)
    vectorDialogVisible.value = true
  } catch (err) {
    showToast('error', errorMessage(err))
  }
}

function vectorMeta(vector) {
  if (Array.isArray(vector)) {
    return t('database.vectorDimension', { count: vector.length })
  }
  return ''
}

function formatScore(score) {
  if (typeof score !== 'number') return score ?? ''
  return score.toFixed(4)
}

onMounted(fetchConfig)

watch(currentAppId, () => {
  debugVectorBody.value = ''
  debugVectorMeta.value = ''
  debugResults.value = []
})
</script>

<style scoped>
.debug-card {
  display: grid;
  gap: 14px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 20px 24px;
  box-shadow: none;
}

.debug-form {
  display: grid;
  gap: 10px;
}

.debug-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.debug-actions .el-button + .el-button {
  margin-left: 0;
}

.debug-topk {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.vector-actions {
  display: flex;
  gap: 8px;
}

.vector-actions .el-button + .el-button {
  margin-left: 0;
}

.vector-body {
  max-height: 260px;
  overflow: auto;
  padding: 12px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

.vector-meta {
  margin-bottom: 10px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
