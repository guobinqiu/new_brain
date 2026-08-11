<template>
  <div class="app">
    <header class="app-header">
      <div class="header-top">
        <h1>RAG Search</h1>
      </div>
      <p class="header-desc">上传 common 或 scoped 知识，在 Dense（语义）、Sparse（关键词）、Hybrid（融合）三种模式间检索</p>
    </header>

    <div class="top-section">
      <!-- Upload -->
      <div class="upload-card">
        <input id="upload-file-input" type="file" multiple class="file-input" accept=".pdf,.txt,.md,.docx,.png,.jpg,.jpeg,.webp,.bmp" @change="onFileSelect" />
        <label for="upload-file-input" class="upload-zone" @dragover.prevent @drop.prevent="onDrop">
          <div class="upload-icon">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          </div>
          <p class="upload-title">{{ selectedFiles.length ? selectedFiles.map(file => file.name).join('、') : '选择文档' }}</p>
          <p class="upload-hint">拖拽文件到这里 · PDF / TXT / MD / DOCX / PNG / JPG / JPEG / WEBP / BMP</p>
        </label>
        <div class="upload-options">
          <input v-model.trim="uploadNamespace" class="field-input" placeholder="namespace" />
          <select v-model="uploadCollectionType" class="field-select">
            <option value="common">common</option>
            <option value="scoped">scoped</option>
          </select>
          <input v-if="uploadCollectionType === 'scoped'" v-model.trim="uploadScopeId" class="field-input" placeholder="scope_id" />
          <div class="upload-actions">
            <button class="primary-btn" :disabled="selectedFiles.length === 0 || uploading" @click="uploadSelectedFiles">{{ uploading ? '上传中' : '上传' }}</button>
          </div>
        </div>
        <div v-if="uploadMsg" :class="['upload-feedback', uploadMsg.type]">{{ uploadMsg.text }}</div>
      </div>

      <!-- Documents -->
      <div class="docs-card">
        <div class="docs-head">
          <h2>文档列表</h2>
          <span class="docs-count">{{ documents.length }}</span>
        </div>
        <div v-if="documents.length === 0" class="docs-empty">暂无文档，上传后自动索引</div>
        <div v-else class="docs-scroll">
          <div v-for="doc in documents" :key="`${doc.collection_type}:${doc.scope_id || ''}:${doc.filename}`" class="doc-row">
            <svg class="doc-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span class="doc-name">{{ doc.filename }}</span>
            <span class="doc-scope">{{ doc.collection_type === 'common' ? 'common' : doc.scope_id }}</span>
            <span class="doc-chunks">{{ doc.chunks }}</span>
            <button class="doc-del" @click="deleteDoc(doc)">✕</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Search Section -->
    <div class="search-section">
      <div class="search-row-1">
        <div class="mode-tabs">
          <button :class="['mode-tab', { active: mode === 'hybrid' }]" @click="mode = 'hybrid'">Hybrid</button>
          <button :class="['mode-tab', { active: mode === 'dense' }]" @click="mode = 'dense'">Dense</button>
          <button :class="['mode-tab', { active: mode === 'sparse' }]" @click="mode = 'sparse'">Sparse</button>
        </div>
      </div>
      <div class="search-row-3">
        <div class="scope-controls">
          <span class="scope-title">namespace</span>
          <input v-model.trim="searchNamespace" class="field-input compact" placeholder="namespace" @change="onSearchNamespaceChange" />
        </div>
      </div>
      <div class="search-row-3">
        <div class="scope-controls">
          <span class="scope-title">scope_ids</span>
          <input v-model.trim="scopeIdsText" class="field-input scopes" placeholder="scope_ids，多个用逗号分隔" />
        </div>
      </div>
      <div v-if="availableScopeIds.length" class="search-row-3">
        <div class="scope-list">
          <button class="scope-chip" @click="selectAllScopes">全部 scope</button>
          <button v-for="scopeId in availableScopeIds" :key="scopeId" class="scope-chip" @click="scopeIdsText = scopeId">{{ scopeId }}</button>
        </div>
      </div>
      <div v-if="mode === 'hybrid'" class="search-row-3">
        <div v-if="mode === 'hybrid'" class="balance-control">
          <span class="bal-label">Dense</span>
          <input type="range" min="0" max="1" step="0.05" v-model.number="hybridBalance" @input="onBalanceChange" class="bal-slider" />
          <span class="bal-value">{{ hybridBalance.toFixed(2) }}</span>
          <span class="bal-label" style="text-align:right">Sparse</span>
        </div>
      </div>
      <div class="search-row-3">
        <div class="topk-control">
          <span class="topk-label">返回条数</span>
          <select v-model.number="topK" class="topk-select">
            <option :value="3">3</option>
            <option :value="5">5</option>
            <option :value="10">10</option>
            <option :value="20">20</option>
          </select>
        </div>
      </div>
      <div class="search-row-3">
        <label v-if="rerankAvailable" class="rerank-control">
          <input type="checkbox" v-model="rerank" class="rerank-checkbox" />
          <span>重排</span>
        </label>
        <div v-if="rerank" class="fetchk-control">
          <span class="cand-label" title="送入检索/重排的候选条数">候选池</span>
          <input type="number" v-model.number="fetchK" :min="topK" class="cand-input" title="送入检索/重排的候选条数" />
        </div>
      </div>
      <div class="search-row-2">
        <div class="search-input-wrap">
          <input v-model="query" type="text" placeholder="输入搜索内容..." @keyup.enter="doSearch" class="search-input" />
          <button @click="doSearch" :disabled="!query.trim() || searching" class="search-btn">{{ searching ? '搜索中' : '搜索' }}</button>
        </div>
      </div>
    </div>

    <!-- Results -->
    <div v-if="searchResults.length > 0" class="results-section">
      <div class="results-bar">
        <span class="results-count">{{ searchResults.length }} 条结果</span>
        <span class="results-mode">模式: {{ lastSearch?.mode }}</span>
        <span class="results-mode">namespace: {{ lastSearch?.namespace }}</span>
        <span v-if="lastSearch?.scopeIds.length" class="results-mode">scope: {{ lastSearch.scopeIds.join(', ') }}</span>
        <span v-if="lastSearch?.mode === 'hybrid'" class="results-balance">平衡: {{ lastSearch.balance.toFixed(2) }} Dense</span>
        <span v-if="searchTime !== null" class="results-elapsed">耗时: {{ searchTime }}ms</span>
      </div>
      <div v-for="(r, i) in searchResults" :key="i" class="result-card">
        <div class="result-head">
          <div class="result-file">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span>{{ r.metadata?.filename || '未知' }}</span>
          </div>
        </div>
        <p class="result-body" v-html="escapeHtml(r.content)"></p>
      </div>
    </div>
    <div v-if="noResults" class="no-results">
      <p>未找到匹配结果</p>
      <p class="no-results-hint">试试其他搜索模式或调整 Sparse / Dense 平衡</p>
    </div>
  </div>

</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const API = '/api'
const selectedFiles = ref([])
const query = ref('')
const mode = ref('hybrid')
const topK = ref(20)
const fetchK = ref(50)
const rerank = ref(false)
const rerankAvailable = ref(false)
const uploadNamespace = ref('default')
const searchNamespace = ref('default')
const uploadCollectionType = ref('common')
const uploadScopeId = ref('')
const scopeIdsText = ref('')
const availableScopeIds = ref([])
const searchConfig = ref({ dense_weight: 0.5, sparse_weight: 0.5, rrf_k: 60 })
const hybridBalance = ref(0.5)
const documents = ref([])
const searchResults = ref([])
const searchTime = ref(null)
const lastSearch = ref(null)
const searching = ref(false)
const noResults = ref(false)
const uploadMsg = ref(null)
const uploading = ref(false)

function onBalanceChange() {
  searchConfig.value.dense_weight = hybridBalance.value
  searchConfig.value.sparse_weight = 1 - hybridBalance.value
}

async function onDrop(e) {
  const files = e.dataTransfer.files
  selectedFiles.value = files.length ? Array.from(files) : []
}

async function onFileSelect(e) {
  const files = e.target.files
  selectedFiles.value = files.length ? Array.from(files) : []
  e.target.value = ''
}

async function uploadSelectedFiles() {
  if (!selectedFiles.value.length || uploading.value) return
  uploading.value = true
  try {
    const uploaded = await uploadFiles(selectedFiles.value)
    if (uploaded) selectedFiles.value = []
  } finally {
    uploading.value = false
  }
}

async function uploadFiles(files) {
  if (uploadCollectionType.value === 'scoped' && !uploadScopeId.value) {
    uploadMsg.value = { type: 'error', text: 'scoped collection 需要填写 scope_id' }
    return false
  }
  let uploaded = true
  for (const file of files) {
    uploadMsg.value = { type: 'info', text: `正在上传 ${file.name}...` }
    const form = new FormData()
    form.append('file', file)
    form.append('collection_type', uploadCollectionType.value)
    form.append('namespace', uploadNamespace.value || 'default')
    if (uploadCollectionType.value === 'scoped') form.append('scope_id', uploadScopeId.value)
    try {
      const res = await axios.post(`${API}/upload`, form)
      uploadMsg.value = { type: 'success', text: `${res.data.filename} 索引完成（${res.data.chunks} 块）` }
    } catch (err) {
      uploaded = false
      uploadMsg.value = { type: 'error', text: `${file.name}: ${err.response?.data?.detail || err.message}` }
    }
  }
  await fetchDocuments()
  await fetchScopes()
  if (uploaded) uploadMsg.value = { type: 'success', text: '上传完成' }
  return uploaded
}

async function doSearch() {
  if (!query.value.trim()) return
  if (rerank.value && fetchK.value < topK.value) fetchK.value = topK.value
  searching.value = true
  noResults.value = false
  searchResults.value = []
  searchTime.value = null
  try {
    const scopeIds = scopeIdsText.value.split(',').map(s => s.trim()).filter(Boolean)
    const body = {
      query: query.value,
      mode: mode.value,
      top_k: topK.value,
      rerank: rerank.value,
      dense_weight: searchConfig.value.dense_weight,
      sparse_weight: searchConfig.value.sparse_weight,
      rrf_k: searchConfig.value.rrf_k,
      namespace: searchNamespace.value || 'default',
      scope_ids: scopeIds,
    }
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
      namespace: searchNamespace.value || 'default',
      scopeIds,
    }
    noResults.value = searchResults.value.length === 0
  } catch (err) { console.error(err) }
  searching.value = false
}

async function deleteDoc(doc) {
  try {
    const params = {
      collection_type: doc.collection_type || 'common',
      namespace: doc.namespace || searchNamespace.value || 'default',
    }
    if (doc.scope_id) params.scope_id = doc.scope_id
    await axios.delete(`${API}/documents/${encodeURIComponent(doc.filename)}`, { params })
    fetchDocuments()
  } catch (err) { console.error(err) }
}

async function fetchConfig() {
  try {
    const res = await axios.get(`${API}/config`)
    searchConfig.value = res.data
    mode.value = res.data.default_mode ?? mode.value
    rerankAvailable.value = Boolean(res.data.rerank_available)
    rerank.value = Boolean(res.data.rerank && res.data.rerank_available)
    hybridBalance.value = res.data.dense_weight
    topK.value = res.data.top_k ?? topK.value
    fetchK.value = res.data.fetch_k ?? fetchK.value
  } catch (err) { console.error(err) }
}

async function fetchDocuments() {
  try {
    const scopeIds = scopeIdsText.value.split(',').map(s => s.trim()).filter(Boolean)
    const params = new URLSearchParams()
    params.append('collection_type', 'all')
    params.append('namespace', searchNamespace.value || 'default')
    scopeIds.forEach(scopeId => params.append('scope_ids', scopeId))
    const res = await axios.get(`${API}/documents`, { params })
    documents.value = res.data.documents
  }
  catch (err) { console.error(err) }
}

async function fetchScopes() {
  try {
    const res = await axios.get(`${API}/scopes`, { params: { namespace: searchNamespace.value || 'default' } })
    availableScopeIds.value = res.data.scope_ids || []
    if (!scopeIdsText.value && availableScopeIds.value.length) selectAllScopes()
  }
  catch (err) { console.error(err) }
}

async function onSearchNamespaceChange() {
  scopeIdsText.value = ''
  await fetchScopes()
  await fetchDocuments()
}

function selectAllScopes() {
  scopeIdsText.value = availableScopeIds.value.join(', ')
}

onMounted(() => { fetchDocuments(); fetchConfig(); fetchScopes() })

function escapeHtml(text) {
  const el = document.createElement('div')
  el.textContent = text
  return el.innerHTML
}

</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif; background: #f5f6fa; color: #1d1d1f; -webkit-font-smoothing: antialiased; }

.app { max-width: 1100px; margin: 0 auto; padding: 36px 32px; }

/* Header */
.app-header { margin-bottom: 28px; }
.header-top { display: flex; align-items: center; gap: 12px; }
.header-top h1 { font-size: 24px; font-weight: 700; letter-spacing: -0.02em; color: #1d1d1f; }
.header-desc { font-size: 14px; color: #8e8e93; margin-top: 6px; }

/* Top Section */
.top-section { display: flex; gap: 20px; margin-bottom: 20px; }

/* Upload */
.upload-card { flex: 0 0 300px; }
.file-input { position: absolute; width: 1px; height: 1px; opacity: 0; overflow: hidden; pointer-events: none; }
.upload-zone { display: block; background: #fff; border: 2px dashed #d2d5db; border-radius: 14px; padding: 32px 20px; text-align: center; transition: all .25s; cursor: pointer; }
.upload-zone:hover { border-color: #409eff; background: #f8fbff; }
.upload-icon { color: #409eff; margin-bottom: 12px; display: flex; justify-content: center; }
.upload-title { font-size: 15px; font-weight: 500; color: #1d1d1f; margin-bottom: 4px; }
.upload-hint { font-size: 12px; color: #aeaeb2; }
.upload-options { display: grid; grid-template-columns: 1fr; gap: 8px; margin-top: 10px; }
.upload-actions { display: grid; grid-template-columns: 1fr; gap: 8px; }
.primary-btn { height: 34px; border: none; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.primary-btn { background: #409eff; color: #fff; }
.primary-btn:hover:not(:disabled) { background: #1677ff; }
.primary-btn:disabled { background: #a0cfff; cursor: not-allowed; }
.upload-feedback { font-size: 13px; margin-top: 8px; padding: 6px 12px; border-radius: 8px; }
.upload-feedback.info { color: #409eff; background: #e6f2ff; }
.upload-feedback.success { color: #22a67e; background: #e8f8f2; }
.upload-feedback.error { color: #f56a00; background: #fff2e8; }

/* Documents */
.docs-card { flex: 1; background: #fff; border-radius: 14px; padding: 20px 24px; box-shadow: 0 1px 4px rgba(0,0,0,.04); }
.docs-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.docs-head h2 { font-size: 14px; font-weight: 600; color: #1d1d1f; }
.docs-count { font-size: 12px; font-weight: 500; color: #8e8e93; background: #f2f2f5; padding: 0 8px; min-width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; border-radius: 10px; }
.docs-empty { font-size: 13px; color: #aeaeb2; text-align: center; padding: 28px 0; }
.docs-scroll { max-height: 210px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.doc-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 8px; transition: background .15s; }
.doc-row:hover { background: #f5f5f7; }
.doc-icon { flex-shrink: 0; }
.doc-name { flex: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-scope { max-width: 88px; font-size: 11px; color: #6c7680; background: #eef4f8; padding: 1px 8px; border-radius: 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 0; }
.doc-chunks { font-size: 11px; color: #aeaeb2; background: #f2f2f5; padding: 1px 8px; border-radius: 8px; flex-shrink: 0; }
.doc-del { font-size: 12px; border: none; background: none; color: #c7c7cc; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.doc-del:hover { color: #f56a00; background: #fff2e8; }

/* Search Section */
.search-section { position: sticky; bottom: 0; background: #fff; border-radius: 14px; padding: 20px 24px; margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.04); }
.search-row-1 { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.search-row-2 { margin-bottom: 10px; }
.search-row-3 { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }

.mode-tabs { display: flex; gap: 2px; background: #f2f2f5; border-radius: 10px; padding: 3px; flex-shrink: 0; }
.mode-tab { padding: 6px 18px; border: none; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; color: #8e8e93; background: transparent; transition: all .2s; }
.mode-tab.active { background: #fff; color: #1d1d1f; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.mode-tab:hover:not(.active) { color: #666; }

.scope-controls { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; width: 100%; }
.scope-title { width: 76px; font-size: 13px; color: #8e8e93; white-space: nowrap; }
.field-input, .field-select { height: 32px; padding: 5px 10px; border: 1.5px solid #e5e5ea; border-radius: 8px; font-size: 13px; background: #fff; outline: none; min-width: 0; }
.field-input:focus, .field-select:focus { border-color: #409eff; }
.field-input.compact { width: 130px; flex-shrink: 0; }
.field-input.scopes { flex: 1; }
.scope-list { display: flex; flex-wrap: wrap; gap: 6px; padding-left: 84px; }
.scope-chip { border: 1px solid #e5e5ea; background: #fff; color: #6c7680; border-radius: 8px; padding: 4px 8px; font-size: 12px; cursor: pointer; }
.scope-chip:hover { border-color: #409eff; color: #409eff; }

.search-input-wrap { flex: 1; display: flex; gap: 8px; }
.search-input { flex: 1; padding: 8px 16px; border: 1.5px solid #e5e5ea; border-radius: 10px; font-size: 14px; outline: none; transition: border-color .2s; }
.search-input:focus { border-color: #409eff; }
.search-btn { padding: 8px 24px; background: #409eff; color: #fff; border: none; border-radius: 10px; font-size: 14px; font-weight: 500; cursor: pointer; transition: background .2s; }
.search-btn:hover:not(:disabled) { background: #1677ff; }
.search-btn:disabled { background: #a0cfff; cursor: not-allowed; }

.balance-control { display: flex; align-items: center; gap: 10px; flex: 1; max-width: 520px; }
.bal-label { font-size: 12px; color: #aeaeb2; white-space: nowrap; min-width: 40px; }
.bal-slider { flex: 1; accent-color: #409eff; height: 4px; cursor: pointer; }
.bal-value { font-size: 14px; font-weight: 600; color: #409eff; min-width: 36px; text-align: center; }

.topk-control { display: flex; align-items: center; gap: 6px; }
.topk-label { font-size: 13px; color: #8e8e93; }
.topk-select { padding: 5px 10px; border: 1.5px solid #e5e5ea; border-radius: 8px; font-size: 13px; background: #fff; cursor: pointer; outline: none; }
.fetchk-control { display: flex; align-items: center; gap: 6px; }
.cand-label { font-size: 13px; color: #8e8e93; white-space: nowrap; }
.cand-input { width: 72px; padding: 5px 10px; border: 1.5px solid #e5e5ea; border-radius: 8px; font-size: 13px; background: #fff; outline: none; }
.cand-input:focus { border-color: #409eff; }
.rerank-control { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #8e8e93; cursor: pointer; user-select: none; }
.rerank-checkbox { accent-color: #409eff; width: 15px; height: 15px; cursor: pointer; }

/* Results */
.results-section { background: #fff; border-radius: 14px; padding: 0 24px; box-shadow: 0 1px 4px rgba(0,0,0,.04); margin-bottom: 20px; }
.results-bar { display: flex; align-items: center; gap: 16px; padding: 16px 0; border-bottom: 1px solid #f2f2f5; }
.results-count { font-size: 14px; font-weight: 600; color: #1d1d1f; }
.results-mode, .results-balance, .results-elapsed { font-size: 12px; color: #8e8e93; }

.result-card { padding: 18px 0; border-bottom: 1px solid #f5f5f7; }
.result-card:last-child { border-bottom: none; }
.result-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.result-file { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #8e8e93; flex: 1; overflow: hidden; }
.result-file span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-body { font-size: 14px; line-height: 1.8; color: #3a3a3c; }

.no-results { text-align: center; padding: 48px 24px; }
.no-results p { font-size: 14px; color: #8e8e93; }
.no-results-hint { font-size: 12px; color: #aeaeb2; margin-top: 6px; }
</style>
