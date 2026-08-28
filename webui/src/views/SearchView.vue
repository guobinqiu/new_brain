<template>
  <main class="search-view">
    <!-- Search Section -->
    <div class="search-section">
      <div class="search-row-1">
        <el-radio-group v-model="mode">
          <el-radio-button value="hybrid">Hybrid</el-radio-button>
          <el-radio-button value="dense">Dense</el-radio-button>
          <el-radio-button value="sparse">Sparse</el-radio-button>
        </el-radio-group>
      </div>
      <div class="search-row-3">
        <div class="scope-controls">
          <span class="scope-title">File IDs</span>
          <el-input v-model.trim="fileIdsText" :placeholder="t('search.fileIdsPlaceholder')" class="scopes" />
        </div>
      </div>
      <div v-if="mode === 'hybrid'" class="search-row-3">
        <div v-if="mode === 'hybrid'" class="balance-control">
          <span class="bal-label">Dense</span>
          <el-slider v-model="hybridBalance" :min="0" :max="1" :step="0.05" @input="onBalanceChange" style="flex: 1" />
          <span class="bal-value">{{ hybridBalance.toFixed(2) }}</span>
          <span class="bal-label" style="text-align:right">Sparse</span>
        </div>
      </div>
      <div class="search-row-3">
        <div class="topk-control">
          <span class="topk-label">{{ t('search.topK') }}</span>
          <el-select v-model="topK" style="width: 110px">
            <el-option :value="3" label="3" />
            <el-option :value="5" label="5" />
            <el-option :value="10" label="10" />
            <el-option :value="20" label="20" />
          </el-select>
        </div>
      </div>
      <div class="search-row-3">
        <el-checkbox v-if="rerankAvailable" v-model="rerank" class="rerank-control">{{ t('search.rerank') }}</el-checkbox>
        <div v-if="rerank" class="fetchk-control">
          <span class="cand-label" :title="t('search.fetchKTitle')">{{ t('search.fetchK') }}</span>
          <el-input-number v-model="fetchK" :min="topK" :title="t('search.fetchKTitle')" style="width: 120px" />
        </div>
      </div>
      <div class="search-row-2">
        <div class="search-input-wrap">
          <el-input v-model="query" :placeholder="t('search.placeholder')" @keyup.enter="doSearch" />
          <el-button type="primary" :disabled="!query.trim() || searching" :loading="searching" @click="doSearch">{{ searching ? t('search.searching') : t('search.submit') }}</el-button>
        </div>
      </div>
    </div>

    <!-- Results -->
    <div v-if="searchResults.length > 0" class="results-section">
      <div class="results-bar">
        <span class="results-count">{{ t('search.resultCount', { count: searchResults.length }) }}</span>
        <span class="results-mode">{{ t('search.mode') }}: {{ lastSearch?.mode }}</span>
        <span class="results-mode">{{ t('search.files') }}: {{ lastSearch?.fileIds?.length ? lastSearch.fileIds.length : t('common.all') }}</span>
        <span v-if="lastSearch?.mode === 'hybrid'" class="results-balance">{{ t('search.balance') }}: {{ lastSearch.balance.toFixed(2) }} Dense</span>
        <span v-if="searchTime !== null" class="results-elapsed">{{ t('search.elapsed') }}: {{ searchTime }}ms</span>
      </div>
      <div v-for="(r, i) in searchResults" :key="i" class="result-card">
        <div class="result-head">
          <div class="result-file">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span>{{ r.metadata?.filename || '未知' }}</span>
          </div>
          <span v-if="typeof r.score === 'number'" class="result-score">{{ t('search.score') }}: {{ formatScore(r.score) }}</span>
        </div>
        <p class="result-body" v-html="escapeHtml(r.content)"></p>
      </div>
    </div>
    <div v-if="noResults" class="no-results">
      <p>{{ t('search.noResults') }}</p>
      <p class="no-results-hint">{{ t('search.noResultsHint') }}</p>
    </div>
  </main>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import axios from '../utils/api'
import { useActiveAppStore } from '../stores/activeApp'
import { parseFileIds, escapeHtml } from '../utils/format'
import { errorMessage, showToast } from '../utils/toast'

const API = '/api'
const { t } = useI18n()
const activeAppStore = useActiveAppStore()
const route = useRoute()
const currentAppId = computed(() => route.params.app_id || activeAppStore.appId)

const query = ref('')
const mode = ref('hybrid')
const topK = ref(5)
const fetchK = ref(20)
const rerank = ref(false)
const rerankAvailable = ref(false)
const fileIdsText = ref('')
const hybridBalance = ref(0.5)
const searchConfig = ref({ dense_weight: 0.5, sparse_weight: 0.5, rrf_k: 60 })
const searchResults = ref([])
const searchTime = ref(null)
const lastSearch = ref(null)
const searching = ref(false)
const noResults = ref(false)

function onBalanceChange() {
  searchConfig.value.dense_weight = hybridBalance.value
  searchConfig.value.sparse_weight = 1 - hybridBalance.value
}

function searchFileIds() {
  return parseFileIds(fileIdsText.value)
}

function formatScore(score) {
  return Number(score).toFixed(4)
}

async function doSearch() {
  if (!query.value.trim()) return
  if (rerank.value && fetchK.value < topK.value) fetchK.value = topK.value
  searching.value = true
  noResults.value = false
  searchResults.value = []
  searchTime.value = null
  try {
    const fileIds = searchFileIds()
    const body = {
      query: query.value,
      mode: mode.value,
      top_k: topK.value,
      rerank: rerank.value,
      dense_weight: searchConfig.value.dense_weight,
      sparse_weight: searchConfig.value.sparse_weight,
      rrf_k: searchConfig.value.rrf_k,
    }
    if (currentAppId.value) body.app_id = currentAppId.value
    if (fileIds.length) body.file_ids = fileIds
    if (rerank.value) body.fetch_k = fetchK.value
    const res = await axios.post(`${API}/search`, body)
    searchResults.value = res.data.results
    searchTime.value = res.data.elapsed_ms
    lastSearch.value = {
      query: query.value,
      mode: mode.value,
      balance: hybridBalance.value,
      topK: topK.value,
      rerank: rerank.value,
      fetchK: rerank.value ? fetchK.value : null,
      fileIds,
    }
    noResults.value = searchResults.value.length === 0
  } catch (err) {
    showToast('error', errorMessage(err, 'Search failed'))
  }
  searching.value = false
}

async function fetchConfig() {
  try {
    const res = await axios.get(`${API}/config`)
    searchConfig.value = res.data
    mode.value = res.data.default_mode ?? mode.value
    rerankAvailable.value = Boolean(res.data.rerank_available)
    rerank.value = Boolean(res.data.rerank && res.data.rerank_available)
    hybridBalance.value = res.data.dense_weight ?? 0.5
    topK.value = res.data.top_k ?? topK.value
    fetchK.value = res.data.fetch_k ?? fetchK.value
  } catch (err) { console.error(err) }
}

onMounted(fetchConfig)
</script>
