<template>
  <div class="app">
    <header class="app-header">
      <div class="header-top">
        <h1>RAG Search</h1>
      </div>
      <p class="header-desc">上传文档后按文件范围检索，在 Dense（语义）、Sparse（关键词）、Hybrid（融合）三种模式间切换</p>
    </header>

    <nav class="view-tabs">
      <button :class="['view-tab', { active: activeView === 'search' }]" @click="activeView = 'search'">搜索</button>
      <button :class="['view-tab', { active: activeView === 'upload' }]" @click="activeView = 'upload'; refreshFiles()">上传</button>
      <button :class="['view-tab', { active: activeView === 'monitor' }]" @click="activeView = 'monitor'; fetchMonitor()">监控</button>
      <button :class="['view-tab', { active: activeView === 'database' }]" @click="activeView = 'database'; fetchMonitor(); refreshChunks()">数据库</button>
      <button :class="['view-tab', { active: activeView === 'config' }]" @click="activeView = 'config'; fetchConfig()">配置</button>
    </nav>

    <main v-if="activeView === 'search'" class="search-view">
    <!-- Search Section -->
    <div class="search-section">
      <div class="search-row-1">
        <div class="mode-tabs">
          <button :class="['mode-tab', { active: mode === 'hybrid' }]" @click="mode = 'hybrid'">Hybrid</button>
          <button :class="['mode-tab', { active: mode === 'dense' }]" @click="mode = 'dense'">Dense</button>
          <button :class="['mode-tab', { active: mode === 'sparse' }]" @click="mode = 'sparse'">Sparse</button>
        </div>
      </div>
      <div v-if="showSparseMode" class="search-row-3">
        <div class="scope-controls">
          <span class="scope-title">sparse</span>
          <select v-model="sparseMode" class="field-select compact">
            <option v-for="item in sparseModes" :key="item" :value="item">{{ sparseModeLabel(item) }}</option>
          </select>
        </div>
      </div>
      <div class="search-row-3">
        <div class="scope-controls">
          <span class="scope-title">file_ids</span>
          <input v-model.trim="fileIdsText" class="field-input scopes" placeholder="多个 file_id 用英文逗号分隔；留空为全量搜索" />
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
        <span v-if="lastSearch?.mode !== 'dense'" class="results-mode">sparse: {{ sparseModeLabel(lastSearch?.sparseMode) }}</span>
        <span class="results-mode">文件: {{ lastSearch?.fileIds?.length ? lastSearch.fileIds.length : '全部' }}</span>
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
    </main>

    <main v-if="activeView === 'upload'" class="upload-view">
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
          <div class="upload-actions">
            <button class="primary-btn" :disabled="selectedFiles.length === 0 || uploading" @click="uploadSelectedFiles">{{ uploading ? '上传中' : '上传' }}</button>
          </div>
        </div>
        <div v-if="uploadMsg" :class="['upload-feedback', uploadMsg.type]">{{ uploadMsg.text }}</div>
      </div>

      <div class="files-card">
        <div class="docs-head">
          <h2>上传文件</h2>
          <span class="docs-count">{{ files.length }}{{ filesHasMore ? '+' : '' }}</span>
        </div>
        <div v-if="files.length === 0 && !filesLoading" class="docs-empty">暂无上传文件</div>
        <div v-else class="files-scroll" @scroll="onFilesScroll">
          <div class="files-table">
            <div class="files-head">
              <span>file_id</span>
              <span>filename</span>
              <span>chunks</span>
              <span></span>
            </div>
            <div v-for="file in files" :key="file.id" class="file-row">
              <span class="chunk-id" :title="file.id">{{ file.id }}</span>
              <span class="chunk-name" :title="file.filename">{{ file.filename }}</span>
              <span>{{ file.chunk_count }}</span>
              <button class="file-delete" :disabled="deletingFileId === file.id" @click="deleteFile(file)">{{ deletingFileId === file.id ? '删除中' : '删除' }}</button>
            </div>
          </div>
          <div v-if="filesLoading" class="docs-loading">加载中</div>
          <button v-else-if="filesHasMore" class="docs-more" @click="loadMoreFiles">加载更多</button>
        </div>
      </div>
    </main>

    <main v-if="activeView === 'monitor'" class="monitor-view">
      <!-- Runtime Monitor -->
      <div class="monitor-section">
        <div class="monitor-head">
          <div>
            <h2>运行状态</h2>
            <p>{{ monitorState?.profile?.config_name || '-' }} · {{ monitorState?.profile?.store?.type || '-' }}</p>
          </div>
          <div class="monitor-actions">
            <button class="ghost-btn" @click="fetchMonitor">刷新</button>
          </div>
        </div>
        <div class="monitor-grid">
          <div class="monitor-block">
            <div class="block-title component-title">
              <span>组件</span>
              <span class="status-legend">
                <span><i class="status-dot ready"></i>就绪</span>
                <span><i class="status-dot loading"></i>加载</span>
                <span><i class="status-dot disabled"></i>停用</span>
                <span><i class="status-dot error"></i>错误</span>
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
          <div class="monitor-block trace-block">
            <div class="block-title">查询日志</div>
            <div v-if="searchTraces.length" class="trace-table-wrap">
              <div class="trace-table">
                <div class="trace-table-head">
                  <span>query</span>
                  <span>mode</span>
                  <span>top_k</span>
                  <span>elapsed</span>
                  <span>prepare</span>
                  <span>dense</span>
                  <span>sparse</span>
                  <span>fusion</span>
                  <span>dedupe</span>
                  <span>rerank</span>
                  <span>format</span>
                </div>
                <div v-for="trace in searchTraces" :key="trace.trace_id" class="trace-table-row">
                  <span class="trace-query" :title="trace.query">{{ trace.query }}</span>
                  <span>{{ trace.mode }}<template v-if="trace.mode !== 'dense'">/{{ trace.sparse_mode }}</template></span>
                  <span>{{ trace.top_k }}</span>
                  <strong>{{ ms(trace.elapsed_ms) }}</strong>
                  <span>{{ stageMs(trace, 'prepare_plan') }}</span>
                  <span>{{ stageMs(trace, 'dense') }}</span>
                  <span>{{ stageMs(trace, 'sparse') }}</span>
                  <span>{{ stageMs(trace, 'fusion') }}</span>
                  <span>{{ stageMs(trace, 'dedupe') }}</span>
                  <span>{{ stageMs(trace, 'rerank') }}</span>
                  <span>{{ stageMs(trace, 'format_response') }}</span>
                </div>
              </div>
            </div>
            <div v-else class="trace-empty">暂无查询</div>
          </div>
        </div>
      </div>
    </main>

    <main v-if="activeView === 'database'" class="database-view">
      <div class="monitor-section">
        <div class="monitor-head">
          <div>
            <h2>数据库</h2>
            <p>{{ monitorState?.profile?.store?.type || '-' }} · {{ monitorState?.profile?.store?.collections?.chunks || '-' }}</p>
          </div>
          <div class="monitor-actions">
            <button class="ghost-btn" @click="fetchMonitor(); refreshChunks()">刷新</button>
          </div>
        </div>
        <div class="database-grid">
          <div class="monitor-block">
            <div class="block-title">统计</div>
            <div class="metric-row">
              <div><strong>{{ monitorData?.files ?? 0 }}</strong><span>files</span></div>
              <div><strong>{{ monitorData?.total_chunks ?? 0 }}</strong><span>chunks</span></div>
              <div><strong>{{ chunks.length }}</strong><span>listed</span></div>
            </div>
          </div>
          <div class="monitor-block">
            <div class="block-title">存储</div>
            <div class="kv-list">
              <div><span>地址/路径</span><strong>{{ storeLocation }}</strong></div>
              <div><span>collection</span><strong>{{ monitorState?.profile?.store?.collections?.chunks || '-' }}</strong></div>
              <div><span>sparse 模式</span><strong>{{ sparseModes.map(sparseModeLabel).join(' / ') }}</strong></div>
            </div>
          </div>
        </div>
      </div>

      <div class="chunks-card">
        <div class="docs-head">
          <h2>向量数据</h2>
          <span class="docs-count">{{ chunks.length }}{{ chunksHasMore ? '+' : '' }}</span>
        </div>
        <div v-if="chunks.length === 0 && !chunksLoading" class="docs-empty">暂无向量数据</div>
        <div v-else class="chunks-scroll" @scroll="onChunksScroll">
          <div class="chunks-table">
            <div class="chunks-head">
              <span>chunk_id</span>
              <span>file_id</span>
              <span>s3_url</span>
              <span>filename</span>
              <span>index</span>
              <span>content</span>
            </div>
            <div v-for="chunk in chunks" :key="chunk.id" class="chunk-row">
              <span class="chunk-id" :title="chunk.id">{{ chunk.id }}</span>
              <span class="chunk-id" :title="chunk.file_id">{{ chunk.file_id }}</span>
              <span class="chunk-id" :title="chunk.s3_url">{{ chunk.s3_url }}</span>
              <span class="chunk-name" :title="chunk.filename">{{ chunk.filename }}</span>
              <span>{{ chunk.chunk_index }}</span>
              <span class="chunk-content" :title="chunk.content">{{ chunk.content }}</span>
            </div>
          </div>
          <div v-if="chunksLoading" class="docs-loading">加载中</div>
          <button v-else-if="chunksHasMore" class="docs-more" @click="loadMoreChunks">加载更多</button>
        </div>
      </div>

    </main>

    <main v-if="activeView === 'config'" class="config-view">
      <div class="monitor-section">
        <div class="monitor-head">
          <div>
            <h2>配置</h2>
            <p>{{ configView?.config_name || '-' }}</p>
          </div>
        </div>
        <div class="config-grid">
          <div class="monitor-block">
            <div class="block-title">搜索默认值</div>
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
            <div class="block-title">组件配置</div>
            <div class="kv-list">
              <div><span>dense</span><strong>{{ configComponentModel(configView?.dense) }}</strong></div>
              <div><span>sparse app</span><strong>{{ configComponentModel(configView?.sparse?.app) }}</strong></div>
              <div><span>sparse vector</span><strong>{{ configComponentModel(configView?.sparse?.vector) }}</strong></div>
              <div><span>rerank</span><strong>{{ configComponentModel(configView?.rerank) }}</strong></div>
              <div><span>ocr</span><strong>{{ configComponentModel(configView?.ocr) }}</strong></div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>

</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import axios from 'axios'

const API = '/api'
const activeView = ref('search')
const selectedFiles = ref([])
const query = ref('')
const mode = ref('hybrid')
const topK = ref(20)
const fetchK = ref(50)
const rerank = ref(false)
const rerankAvailable = ref(false)
const sparseMode = ref('app')
const sparseModes = ref(['app'])
const fileIdsText = ref('')
const searchConfig = ref({ dense_weight: 0.5, sparse_weight: 0.5, rrf_k: 60 })
const configView = ref(null)
const hybridBalance = ref(0.5)
const monitorState = ref(null)
const files = ref([])
const filesCursor = ref(null)
const filesHasMore = ref(false)
const filesLoading = ref(false)
const deletingFileId = ref(null)
const chunks = ref([])
const chunksCursor = ref(null)
const chunksHasMore = ref(false)
const chunksLoading = ref(false)
const searchResults = ref([])
const searchTime = ref(null)
const lastSearch = ref(null)
const searching = ref(false)
const noResults = ref(false)
const uploadMsg = ref(null)
const uploading = ref(false)
const showSparseMode = computed(() => sparseModes.value.length > 1 && mode.value !== 'dense')
const monitorData = computed(() => monitorState.value?.data || null)
const searchTraces = computed(() => monitorState.value?.search_traces || [])
const components = computed(() => monitorState.value?.components || [])
const storeLocation = computed(() => {
  const store = monitorState.value?.profile?.store
  return store?.url || store?.uri || store?.persist_dir || '-'
})

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
  let uploaded = true
  const fileIds = []
  for (const file of files) {
    uploadMsg.value = { type: 'info', text: `正在上传 ${file.name}...` }
    const form = new FormData()
    form.append('file', file)
    try {
      const uploadRes = await axios.post(`${API}/upload`, form)
      uploadMsg.value = { type: 'info', text: `正在生成下载签名 ${file.name}...` }
      const presignRes = await axios.post(`${API}/presign`, { s3_url: uploadRes.data.s3_url })
      uploadMsg.value = { type: 'info', text: `正在索引 ${file.name}...` }
      const indexRes = await axios.post(`${API}/index`, {
        presigned_url: presignRes.data.presigned_url,
        s3_url: uploadRes.data.s3_url,
      })
      fileIds.push(indexRes.data.file_id)
      uploadMsg.value = { type: 'success', text: `${file.name} 已索引，file_id: ${indexRes.data.file_id}` }
    } catch (err) {
      uploaded = false
      uploadMsg.value = { type: 'error', text: `${file.name}: ${err.response?.data?.detail || err.message}` }
    }
  }
  await refreshFiles()
  await refreshChunks()
  if (uploaded) uploadMsg.value = { type: 'success', text: `索引完成：${fileIds.join(', ')}` }
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
    const fileIds = searchFileIds()
    const body = {
      query: query.value,
      mode: mode.value,
      sparse_mode: sparseMode.value,
      top_k: topK.value,
      rerank: rerank.value,
      dense_weight: searchConfig.value.dense_weight,
      sparse_weight: searchConfig.value.sparse_weight,
      rrf_k: searchConfig.value.rrf_k,
    }
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
      sparseMode: res.data.sparse_mode || sparseMode.value,
    }
    noResults.value = searchResults.value.length === 0
    fetchMonitor()
  } catch (err) { console.error(err) }
  searching.value = false
}

async function fetchConfig() {
  try {
    const res = await axios.get(`${API}/config`)
    configView.value = res.data
    searchConfig.value = res.data
    mode.value = res.data.default_mode ?? mode.value
    rerankAvailable.value = Boolean(res.data.rerank_available)
    rerank.value = Boolean(res.data.rerank && res.data.rerank_available)
    sparseModes.value = res.data.sparse?.available_modes || ['app']
    sparseMode.value = res.data.sparse?.default_mode || 'app'
    if (!sparseModes.value.includes(sparseMode.value)) sparseMode.value = sparseModes.value[0] || 'app'
    hybridBalance.value = res.data.dense_weight
    topK.value = res.data.top_k ?? topK.value
    fetchK.value = res.data.fetch_k ?? fetchK.value
  } catch (err) { console.error(err) }
}

async function refreshChunks() {
  chunks.value = []
  chunksCursor.value = null
  chunksHasMore.value = false
  await loadMoreChunks()
}

async function refreshFiles() {
  files.value = []
  filesCursor.value = null
  filesHasMore.value = false
  await loadMoreFiles()
}

async function loadMoreFiles() {
  if (filesLoading.value) return
  filesLoading.value = true
  try {
    const params = { limit: 50 }
    if (filesCursor.value) params.cursor = filesCursor.value
    const res = await axios.get(`${API}/files`, { params })
    files.value = files.value.concat(res.data.files || [])
    filesCursor.value = res.data.next_cursor || null
    filesHasMore.value = Boolean(res.data.has_more)
  }
  catch (err) { console.error(err) }
  finally { filesLoading.value = false }
}

async function deleteFile(file) {
  if (!file?.id || deletingFileId.value) return
  deletingFileId.value = file.id
  uploadMsg.value = { type: 'info', text: `正在删除 ${file.filename}...` }
  try {
    const res = await axios.delete(`${API}/files/${encodeURIComponent(file.id)}`)
    uploadMsg.value = { type: 'success', text: `${file.filename} 已删除，删除 ${res.data.deleted_chunks} 个分块` }
    await refreshFiles()
    await refreshChunks()
    fetchMonitor()
  } catch (err) {
    uploadMsg.value = { type: 'error', text: `${file.filename}: ${err.response?.data?.detail || err.message}` }
  } finally {
    deletingFileId.value = null
  }
}

async function loadMoreChunks() {
  if (chunksLoading.value) return
  chunksLoading.value = true
  try {
    const params = { limit: 50 }
    if (chunksCursor.value) params.cursor = chunksCursor.value
    const res = await axios.get(`${API}/chunks`, { params })
    chunks.value = chunks.value.concat(res.data.chunks || [])
    chunksCursor.value = res.data.next_cursor || null
    chunksHasMore.value = Boolean(res.data.has_more)
  }
  catch (err) { console.error(err) }
  finally { chunksLoading.value = false }
}

function onChunksScroll(event) {
  const el = event.target
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24 && chunksHasMore.value) {
    loadMoreChunks()
  }
}

function onFilesScroll(event) {
  const el = event.target
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24 && filesHasMore.value) {
    loadMoreFiles()
  }
}

async function fetchMonitor() {
  try {
    const res = await axios.get(`${API}/monitor`)
    monitorState.value = res.data
  } catch (err) { console.error(err) }
}

function searchFileIds() {
  return Array.from(new Set(fileIdsText.value.split(',').map(item => item.trim()).filter(Boolean)))
}

function componentModelText(item) {
  if (!item.model) return 'N/A'
  return item.mode ? `${item.model}（${item.mode}）` : item.model
}

function configComponentModel(item) {
  if (!item || item.enable === false) return 'disabled'
  return item.model_name || item.name || item.type || '-'
}

function sparseModeLabel(value) {
  if (value === 'vector') return 'Vector'
  return 'App BM25'
}

function stageMs(trace, name) {
  const stage = (trace.stages || []).find(item => item.name === name)
  return stage ? ms(stage.elapsed_ms) : '-'
}

function ms(value) {
  if (value === null || value === undefined) return '-'
  return `${Number(value).toFixed(1)}`
}

onMounted(() => { refreshFiles(); refreshChunks(); fetchConfig(); fetchMonitor() })

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

.view-tabs { display: flex; gap: 4px; background: #fff; border-radius: 12px; padding: 4px; margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.04); width: fit-content; }
.view-tab { min-width: 76px; height: 32px; border: none; border-radius: 9px; background: transparent; color: #8e8e93; font-size: 13px; font-weight: 500; cursor: pointer; }
.view-tab.active { background: #1d1d1f; color: #fff; }
.view-tab:hover:not(.active) { background: #f5f5f7; color: #1d1d1f; }

/* Upload */
.upload-card, .files-card { background: #fff; border-radius: 14px; padding: 20px 24px; margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.04); }
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
.files-scroll { max-height: 360px; overflow: auto; }
.files-table { min-width: 840px; display: grid; gap: 4px; }
.files-head, .file-row { display: grid; grid-template-columns: minmax(240px, 1.3fr) minmax(260px, 1.4fr) 72px 72px; align-items: center; gap: 8px; font-size: 12px; }
.files-head { color: #8e8e93; font-weight: 600; padding: 0 8px 6px; border-bottom: 1px solid #f0f1f4; }
.file-row { min-height: 34px; color: #6c7680; padding: 6px 8px; border-radius: 8px; background: #fff; border: 1px solid #f0f1f4; }
.file-delete { height: 26px; border: 1px solid #ffd6c2; border-radius: 7px; background: #fff7f2; color: #f56a00; font-size: 12px; cursor: pointer; }
.file-delete:hover:not(:disabled) { border-color: #f56a00; background: #fff2e8; }
.file-delete:disabled { color: #c7c7cc; border-color: #e5e5ea; background: #f5f5f7; cursor: not-allowed; }

/* Chunks */
.chunks-card { background: #fff; border-radius: 14px; padding: 20px 24px; margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.04); }
.docs-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.docs-head h2 { font-size: 14px; font-weight: 600; color: #1d1d1f; }
.docs-count { font-size: 12px; font-weight: 500; color: #8e8e93; background: #f2f2f5; padding: 0 8px; min-width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; border-radius: 10px; }
.docs-empty { font-size: 13px; color: #aeaeb2; text-align: center; padding: 28px 0; }
.chunks-scroll { max-height: 420px; overflow: auto; }
.chunks-table { min-width: 1220px; display: grid; gap: 4px; }
.chunks-head, .chunk-row { display: grid; grid-template-columns: minmax(150px, .9fr) minmax(190px, 1fr) minmax(260px, 1.3fr) minmax(130px, .8fr) 54px minmax(280px, 1.6fr); align-items: center; gap: 8px; font-size: 12px; }
.chunks-head { color: #8e8e93; font-weight: 600; padding: 0 8px 6px; border-bottom: 1px solid #f0f1f4; }
.chunk-row { min-height: 34px; color: #6c7680; padding: 6px 8px; border-radius: 8px; background: #fff; border: 1px solid #f0f1f4; }
.chunk-id { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chunk-name, .chunk-content { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chunk-content { color: #1d1d1f; }
.docs-loading { text-align: center; font-size: 12px; color: #8e8e93; padding: 10px 0; }
.docs-more { height: 30px; border: 1px solid #e5e5ea; border-radius: 8px; background: #fff; color: #6c7680; font-size: 12px; cursor: pointer; }
.docs-more:hover { border-color: #409eff; color: #409eff; }

/* Monitor */
.monitor-section { background: #fff; border-radius: 14px; padding: 18px 22px; margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.04); }
.monitor-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.monitor-head h2 { font-size: 14px; font-weight: 600; color: #1d1d1f; }
.monitor-head p { font-size: 12px; color: #8e8e93; margin-top: 3px; }
.monitor-actions { display: flex; align-items: center; gap: 8px; }
.ghost-btn { height: 30px; padding: 0 12px; border: 1px solid #e5e5ea; border-radius: 8px; background: #fff; color: #6c7680; font-size: 12px; cursor: pointer; }
.ghost-btn:hover { border-color: #409eff; color: #409eff; }
.ghost-btn:disabled { color: #c7c7cc; cursor: not-allowed; }
.ghost-btn:disabled:hover { border-color: #e5e5ea; color: #c7c7cc; }
.monitor-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.database-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.config-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.monitor-block { min-width: 0; border: 1px solid #f0f1f4; border-radius: 10px; padding: 12px; background: #fcfcfd; }
.trace-block { grid-column: 1 / -1; }
.block-title { font-size: 12px; font-weight: 600; color: #6c7680; margin-bottom: 10px; }
.component-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.status-legend { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; color: #8e8e93; font-size: 11px; font-weight: 500; }
.status-legend span { display: inline-flex; align-items: center; gap: 4px; }
.component-list { display: grid; gap: 7px; }
.component-row { display: grid; grid-template-columns: 8px minmax(92px, auto) minmax(0, 1fr); align-items: center; gap: 7px; font-size: 12px; color: #6c7680; min-width: 0; }
.component-row strong { color: #1d1d1f; font-weight: 500; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.component-name { color: #6c7680; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #c7c7cc; }
.status-dot.ready { background: #22a67e; }
.status-dot.loading { background: #f5b342; }
.status-dot.disabled { background: #c7c7cc; }
.status-dot.error { background: #f56a00; }
.kv-list { display: grid; gap: 7px; }
.kv-list div { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; color: #8e8e93; }
.kv-list strong { color: #1d1d1f; font-weight: 500; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.metric-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.metric-row div { border-radius: 8px; background: #fff; padding: 9px 8px; text-align: center; border: 1px solid #f0f1f4; }
.metric-row strong { display: block; font-size: 16px; color: #1d1d1f; }
.metric-row span { font-size: 11px; color: #8e8e93; }
.scope-mini { margin-top: 8px; font-size: 12px; color: #8e8e93; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-table-wrap { overflow-x: auto; }
.trace-table { min-width: 920px; display: grid; gap: 4px; }
.trace-table-head, .trace-table-row { display: grid; grid-template-columns: minmax(160px, 1.8fr) 100px 46px repeat(8, 72px); align-items: center; gap: 8px; font-size: 12px; }
.trace-table-head { color: #8e8e93; font-weight: 600; padding: 0 8px 6px; border-bottom: 1px solid #f0f1f4; }
.trace-table-row { min-height: 32px; color: #6c7680; padding: 6px 8px; border-radius: 8px; background: #fff; border: 1px solid #f0f1f4; }
.trace-table-row strong { color: #409eff; font-weight: 600; }
.trace-query { color: #1d1d1f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-empty { font-size: 12px; color: #aeaeb2; padding: 18px 0; text-align: center; }

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
