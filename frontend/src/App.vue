<template>
  <div :class="['app', `theme-${theme}`]">
    <div v-if="!authToken" class="login-tools">
      <div class="switch-group">
        <button :class="['switch-btn', { active: lang === 'zh' }]" @click="setLang('zh')">中</button>
        <button :class="['switch-btn', { active: lang === 'en' }]" @click="setLang('en')">EN</button>
      </div>
      <div class="switch-group">
        <button :class="['switch-btn', { active: theme === 'light' }]" @click="setTheme('light')">{{ t('theme.light') }}</button>
        <button :class="['switch-btn', { active: theme === 'dark' }]" @click="setTheme('dark')">{{ t('theme.dark') }}</button>
      </div>
    </div>

    <header v-if="authToken" class="app-header">
      <div class="header-top">
        <div>
          <h1>{{ t('app.title') }}</h1>
          <p class="header-desc">{{ t('app.desc') }}</p>
        </div>
        <div class="header-actions">
          <div class="switch-group">
            <button :class="['switch-btn', { active: lang === 'zh' }]" @click="setLang('zh')">中</button>
            <button :class="['switch-btn', { active: lang === 'en' }]" @click="setLang('en')">EN</button>
          </div>
          <div class="switch-group">
            <button :class="['switch-btn', { active: theme === 'light' }]" @click="setTheme('light')">{{ t('theme.light') }}</button>
            <button :class="['switch-btn', { active: theme === 'dark' }]" @click="setTheme('dark')">{{ t('theme.dark') }}</button>
          </div>
          <button v-if="authToken" class="header-logout" @click="logout">{{ t('auth.logout') }}</button>
        </div>
      </div>
    </header>

    <main v-if="!authToken" class="login-view">
      <form class="login-card" @submit.prevent="login">
        <div>
          <h2>{{ t('auth.title') }}</h2>
          <p>{{ t('auth.desc') }}</p>
        </div>
        <label>
          <span>{{ t('auth.username') }}</span>
          <input v-model.trim="loginForm.username" autocomplete="username" class="field-input" />
        </label>
        <label>
          <span>{{ t('auth.password') }}</span>
          <input v-model="loginForm.password" type="password" autocomplete="current-password" class="field-input" />
        </label>
        <button class="primary-btn login-submit">{{ t('auth.login') }}</button>
        <div v-if="loginError" class="upload-feedback error">{{ loginError }}</div>
      </form>
    </main>

    <template v-else>
    <nav class="view-tabs">
      <button :class="['view-tab', { active: activeView === 'upload' }]" @click="activeView = 'upload'; fetchFiles()">{{ t('nav.upload') }}</button>
      <button :class="['view-tab', { active: activeView === 'database' }]" @click="activeView = 'database'; fetchChunks()">{{ t('nav.database') }}</button>
      <button :class="['view-tab', { active: activeView === 'search' }]" @click="activeView = 'search'">{{ t('nav.search') }}</button>
      <button :class="['view-tab', { active: activeView === 'monitor' }]" @click="activeView = 'monitor'">{{ t('nav.monitor') }}</button>
      <button :class="['view-tab', { active: activeView === 'logs' }]" @click="activeView = 'logs'; startLogStream()">{{ t('nav.logs') }}</button>
      <button :class="['view-tab', { active: activeView === 'config' }]" @click="activeView = 'config'; fetchConfig()">{{ t('nav.config') }}</button>
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
      <div class="search-row-3">
        <div class="scope-controls">
          <span class="scope-title">File IDs</span>
          <input v-model.trim="fileIdsText" class="field-input scopes" :placeholder="t('search.fileIdsPlaceholder')" />
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
          <span class="topk-label">{{ t('search.topK') }}</span>
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
          <span>{{ t('search.rerank') }}</span>
        </label>
        <div v-if="rerank" class="fetchk-control">
          <span class="cand-label" :title="t('search.fetchKTitle')">{{ t('search.fetchK') }}</span>
          <input type="number" v-model.number="fetchK" :min="topK" class="cand-input" :title="t('search.fetchKTitle')" />
        </div>
      </div>
      <div class="search-row-2">
        <div class="search-input-wrap">
          <input v-model="query" type="text" :placeholder="t('search.placeholder')" @keyup.enter="doSearch" class="search-input" />
          <button @click="doSearch" :disabled="!query.trim() || searching" class="search-btn">{{ searching ? t('search.searching') : t('search.submit') }}</button>
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
        </div>
        <p class="result-body" v-html="escapeHtml(r.content)"></p>
      </div>
    </div>
    <div v-if="noResults" class="no-results">
      <p>{{ t('search.noResults') }}</p>
      <p class="no-results-hint">{{ t('search.noResultsHint') }}</p>
    </div>
    </main>

    <main v-if="activeView === 'upload'" class="upload-view">
      <div class="upload-card">
        <input id="upload-file-input" type="file" multiple class="file-input" accept=".pdf,.txt,.md,.docx,.png,.jpg,.jpeg,.webp,.bmp" @change="onFileSelect" />
        <label for="upload-file-input" class="upload-zone" @dragover.prevent @drop.prevent="onDrop">
          <div class="upload-icon">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          </div>
          <p class="upload-title">{{ selectedFiles.length ? selectedFiles.map(file => file.name).join('、') : t('upload.choose') }}</p>
          <p class="upload-hint">{{ t('upload.hint') }}</p>
        </label>
        <div class="upload-options">
          <div class="upload-actions">
            <button class="primary-btn" :disabled="selectedFiles.length === 0 || uploading" @click="uploadSelectedFiles">{{ uploading ? t('upload.uploading') : t('upload.submit') }}</button>
          </div>
        </div>
        <div v-if="uploadMsg" :class="['upload-feedback', uploadMsg.type]">{{ uploadMsg.text }}</div>
      </div>

      <div class="files-card">
        <div class="docs-head">
          <h2>{{ t('upload.files') }}</h2>
          <span class="docs-count">{{ files.length }}{{ filesHasMore ? '+' : '' }}</span>
        </div>
        <div v-if="files.length === 0 && !filesLoading" class="docs-empty">{{ t('upload.empty') }}</div>
        <div v-else class="files-scroll" @scroll="onFilesScroll">
          <div class="files-table">
            <div class="files-head">
              <span>file_id</span>
              <span>filename</span>
              <span>created_at</span>
              <span>chunks</span>
              <span></span>
            </div>
            <div v-for="file in files" :key="file.id" class="file-row">
              <span class="chunk-id" :title="file.id">{{ file.id }}</span>
              <span class="chunk-name" :title="file.filename">{{ file.filename }}</span>
              <span>{{ shortTime(file.created_at) }}</span>
              <span>{{ file.chunk_count }}</span>
              <button class="file-delete" :disabled="deletingFileId === file.id" @click="deleteFile(file)">{{ deletingFileId === file.id ? t('common.deleting') : t('common.delete') }}</button>
            </div>
          </div>
          <div v-if="filesLoading" class="docs-loading">{{ t('common.loading') }}</div>
          <button v-else-if="filesHasMore" class="docs-more" @click="fetchNextFiles">{{ t('common.loadMore') }}</button>
        </div>
      </div>
    </main>

    <main v-if="activeView === 'monitor'" class="monitor-view">
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
        <div class="monitor-block trace-block">
          <div class="block-title job-title">
            <span>{{ t('monitor.indexJobs') }}</span>
            <div class="job-filters">
              <button v-for="filter in jobFilters" :key="filter" :class="['job-filter', { active: indexJobFilter === filter }]" @click="indexJobFilter = filter">{{ t(`monitor.jobFilter.${filter}`) }}</button>
              <button class="ghost-btn mini" @click="fetchIndexJobs">{{ t('common.refresh') }}</button>
            </div>
          </div>
          <div v-if="filteredIndexJobs.length" class="trace-table-wrap job-table-wrap" @scroll="onIndexJobsScroll">
            <div class="job-table">
              <div class="job-table-head">
                <span>status</span>
                <span>job_id</span>
                <span>filename</span>
                <span>file_id</span>
                <span>chunks</span>
                <span>error</span>
                <span>created</span>
                <span>ended</span>
              </div>
              <div v-for="job in filteredIndexJobs" :key="job.job_id" class="job-table-row">
                <span :class="['job-status', jobStatusClass(job.status)]">{{ jobStatusText(job.status) }}</span>
                <span class="chunk-id" :title="job.job_id">{{ job.job_id }}</span>
                <span class="chunk-name" :title="job.filename">{{ job.filename || '-' }}</span>
                <span class="chunk-id" :title="job.file_id">{{ job.file_id || '-' }}</span>
                <span>{{ job.chunk_count ?? '-' }}</span>
                <span class="job-error" :title="job.error">{{ job.error || '-' }}</span>
                <span>{{ shortTime(job.created_at || job.enqueued_at) }}</span>
                <span>{{ shortTime(job.ended_at) }}</span>
              </div>
            </div>
            <div v-if="indexJobsLoading" class="docs-loading">{{ t('common.loading') }}</div>
            <button v-else-if="indexJobsHasMore" class="docs-more" @click="fetchNextIndexJobs">{{ t('common.loadMore') }}</button>
          </div>
          <div v-else-if="indexJobsError" class="trace-empty error-text">{{ indexJobsError }}</div>
          <div v-else class="trace-empty">{{ t('monitor.noIndexJobs') }}</div>
        </div>
        <div class="monitor-block trace-block">
          <div class="block-title job-title">
            <span>{{ t('monitor.traces') }}</span>
            <button class="ghost-btn mini" @click="fetchTraces">{{ t('common.refresh') }}</button>
          </div>
          <div v-if="traces.length" class="trace-table-wrap trace-list-wrap" @scroll="onTracesScroll">
            <div class="trace-table">
              <div class="trace-table-head">
                <span>{{ t('trace.columns.time') }}</span>
                <span>{{ t('trace.columns.query') }}</span>
                <span>{{ t('trace.columns.mode') }}</span>
                <span>{{ t('trace.columns.topK') }}</span>
                <span>{{ t('trace.columns.elapsed') }}</span>
                <span>{{ t('trace.columns.prepare') }}</span>
                <span>{{ t('trace.columns.dense') }}</span>
                <span>{{ t('trace.columns.sparse') }}</span>
                <span>{{ t('trace.columns.fusion') }}</span>
                <span>{{ t('trace.columns.dedupe') }}</span>
                <span>{{ t('trace.columns.rerank') }}</span>
                <span>{{ t('trace.columns.format') }}</span>
              </div>
              <div v-for="trace in traces" :key="trace.trace_id" class="trace-table-row">
                <span>{{ shortTime(trace.created_at) }}</span>
                <span class="trace-query" :title="trace.query">{{ trace.query }}</span>
                <span>{{ trace.mode }}</span>
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
            <div v-if="tracesLoading" class="docs-loading">{{ t('common.loading') }}</div>
            <button v-else-if="tracesHasMore" class="docs-more" @click="fetchNextTraces">{{ t('common.loadMore') }}</button>
          </div>
          <div v-else class="trace-empty">{{ t('monitor.noTraces') }}</div>
        </div>
      </div>
    </main>

    <main v-if="activeView === 'logs'" class="logs-view">
      <div class="monitor-section">
        <div class="monitor-head">
          <div>
            <h2>{{ t('logs.title') }}</h2>
            <p>{{ t('logs.desc') }}</p>
          </div>
        </div>
        <div class="monitor-block trace-block">
          <pre v-if="logs.length" ref="logsBox" class="logs-box">{{ logs.map(formatLogLine).join('\n') }}</pre>
          <div v-else class="trace-empty">{{ t('logs.empty') }}</div>
        </div>
      </div>
    </main>

    <main v-if="activeView === 'database'" class="database-view">
      <div class="chunks-card">
        <div class="docs-head">
          <div class="docs-title">
            <h2>{{ t('database.chunks') }}</h2>
            <span class="docs-count">{{ chunks.length }}{{ chunksHasMore ? '+' : '' }}</span>
          </div>
        </div>
        <div class="chunk-filter">
          <span>File IDs</span>
          <input v-model.trim="databaseFileIdsText" class="field-input" :placeholder="t('database.fileIdsPlaceholder')" @keyup.enter="fetchChunks" />
          <button class="ghost-btn" @click="fetchChunks">{{ t('database.query') }}</button>
        </div>
        <div v-if="chunks.length === 0 && !chunksLoading" class="docs-empty">{{ t('database.empty') }}</div>
        <div v-else class="chunks-scroll" @scroll="onChunksScroll">
          <div class="chunks-table">
            <div class="chunks-head">
              <span>chunk_id</span>
              <span>file_id</span>
              <span>s3_url</span>
              <span>filename</span>
              <span>created_at</span>
              <span>chunk_index</span>
              <span>content</span>
            </div>
            <div v-for="chunk in chunks" :key="chunk.id" class="chunk-row">
              <span class="chunk-id" :title="chunk.id">{{ chunk.id }}</span>
              <span class="copy-cell">
                <span class="chunk-id" :title="chunk.file_id">{{ chunk.file_id }}</span>
                <button class="copy-btn" @click="copyText(chunk.file_id)">{{ t('common.copy') }}</button>
              </span>
              <span class="copy-cell">
                <span class="chunk-id" :title="chunk.s3_url">{{ chunk.s3_url }}</span>
                <button class="copy-btn" @click="copyText(chunk.s3_url)">{{ t('common.copy') }}</button>
              </span>
              <span class="chunk-name" :title="chunk.filename">{{ chunk.filename }}</span>
              <span>{{ shortTime(chunk.created_at) }}</span>
              <span>{{ chunk.chunk_index }}</span>
              <span class="copy-cell">
                <span class="chunk-content" :title="chunk.content">{{ chunk.content }}</span>
                <button class="copy-btn" @click="copyText(chunk.content)">{{ t('common.copy') }}</button>
              </span>
            </div>
          </div>
          <div v-if="chunksLoading" class="docs-loading">{{ t('common.loading') }}</div>
          <button v-else-if="chunksHasMore" class="docs-more" @click="fetchNextChunks">{{ t('common.loadMore') }}</button>
        </div>
      </div>

    </main>

    <main v-if="activeView === 'config'" class="config-view">
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
              <div><span>collection</span><strong>{{ configView?.store?.collections?.chunks || '-' }}</strong></div>
            </div>
          </div>
        </div>
      </div>
    </main>
    </template>
  </div>

</template>

<script setup>
import { computed, ref, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import axios from 'axios'

const API = '/api'
const { t, locale } = useI18n()
const theme = ref(localStorage.getItem('rag_theme') || 'light')
const authToken = ref(localStorage.getItem('rag_token') || '')
const loginForm = ref({ username: 'admin', password: '' })
const loginError = ref('')
const activeView = ref('upload')
const selectedFiles = ref([])
const query = ref('')
const mode = ref('hybrid')
const topK = ref(20)
const fetchK = ref(50)
const rerank = ref(false)
const rerankAvailable = ref(false)
const fileIdsText = ref('')
const databaseFileIdsText = ref('')
const databaseAppliedFileIdsText = ref('')
const searchConfig = ref({ dense_weight: 0.5, sparse_weight: 0.5, rrf_k: 60 })
const configView = ref(null)
const hybridBalance = ref(0.5)
const monitorState = ref(null)
const traces = ref([])
const tracesCursor = ref(null)
const tracesHasMore = ref(false)
const tracesLoading = ref(false)
const logs = ref([])
const logsBox = ref(null)
let logStreamController = null
let monitorPollTimer = null
const files = ref([])
const filesCursor = ref(null)
const filesHasMore = ref(false)
const filesLoading = ref(false)
const deletingFileId = ref(null)
const chunks = ref([])
const chunksCursor = ref(null)
const chunksHasMore = ref(false)
const chunksLoading = ref(false)
const indexJobs = ref([])
const indexJobsCursor = ref(null)
const indexJobsHasMore = ref(false)
const indexJobsLoading = ref(false)
const indexJobsError = ref('')
const indexJobFilter = ref('all')
const jobFilters = ['all', 'processing', 'finished', 'failed']
const searchResults = ref([])
const searchTime = ref(null)
const lastSearch = ref(null)
const searching = ref(false)
const noResults = ref(false)
const uploadMsg = ref(null)
const uploading = ref(false)
const components = computed(() => monitorState.value?.components || [])
const filteredIndexJobs = computed(() => {
  if (indexJobFilter.value === 'all') return indexJobs.value
  return indexJobs.value.filter(job => jobStatusClass(job.status) === indexJobFilter.value)
})
const configStoreLocation = computed(() => {
  const store = configView.value?.store
  return store?.url || store?.uri || store?.persist_dir || '-'
})
const lang = computed(() => locale.value)

applyAuthHeader()

axios.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) clearAuth()
    return Promise.reject(error)
  },
)

function setLang(value) {
  locale.value = value
  localStorage.setItem('rag_lang', value)
}

function setTheme(value) {
  theme.value = value
  localStorage.setItem('rag_theme', value)
}

async function login() {
  loginError.value = ''
  try {
    const res = await axios.post(`${API}/auth/token`, {
      grant_type: 'password',
      username: loginForm.value.username,
      password: loginForm.value.password,
    })
    authToken.value = res.data.access_token
    localStorage.setItem('rag_token', authToken.value)
    applyAuthHeader()
    await fetchConfig()
    await fetchMonitor()
    await fetchFiles()
    await fetchChunks()
  } catch (err) {
    loginError.value = err.response?.data?.detail || err.message
  }
}

function logout() {
  clearAuth()
}

function clearAuth() {
  stopLogStream()
  authToken.value = ''
  localStorage.removeItem('rag_token')
  delete axios.defaults.headers.common.Authorization
}

function applyAuthHeader() {
  if (authToken.value) axios.defaults.headers.common.Authorization = `Bearer ${authToken.value}`
}

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
    uploadMsg.value = { type: 'info', text: t('upload.uploadingFile', { name: file.name }) }
    const form = new FormData()
    form.append('file', file)
    try {
      const uploadRes = await axios.post(`${API}/upload`, form)
      uploadMsg.value = { type: 'info', text: t('upload.presigningFile', { name: file.name }) }
      const presignRes = await axios.post(`${API}/presign`, { s3_url: uploadRes.data.s3_url })
      uploadMsg.value = { type: 'info', text: t('upload.indexingFile', { name: file.name }) }
      const indexRes = await axios.post(`${API}/index/jobs`, {
        presigned_url: presignRes.data.presigned_url,
        s3_url: uploadRes.data.s3_url,
      })
      uploadMsg.value = { type: 'success', text: t('upload.indexedFile', { name: file.name, jobId: indexRes.data.job_id }) }
      const job = await waitForIndexJob(indexRes.data.job_id)
      if (job.status === 'finished') {
        fileIds.push(job.file_id)
        uploadMsg.value = { type: 'success', text: t('upload.indexFinished', { name: file.name, fileId: job.file_id }) }
      } else {
        uploaded = false
        uploadMsg.value = { type: 'error', text: t('upload.indexFailed', { name: file.name, error: job.error || job.status }) }
      }
    } catch (err) {
      uploaded = false
      uploadMsg.value = { type: 'error', text: `${file.name}: ${err.response?.data?.detail || err.message}` }
    }
  }
  await fetchFiles()
  await fetchChunks()
  if (uploaded) uploadMsg.value = { type: 'success', text: t('upload.indexedDone', { fileIds: fileIds.join(', ') }) }
  return uploaded
}

async function waitForIndexJob(jobId) {
  for (let i = 0; i < 90; i++) {
    const res = await axios.get(`${API}/index/jobs/${encodeURIComponent(jobId)}`)
    if (['finished', 'failed'].includes(res.data.status)) return res.data
    uploadMsg.value = { type: 'info', text: t('upload.indexWaiting', { jobId, status: res.data.status }) }
    await sleep(2000)
  }
  return { job_id: jobId, status: 'timeout' }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
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
    fetchTraces()
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
    hybridBalance.value = res.data.dense_weight
    topK.value = res.data.top_k ?? topK.value
    fetchK.value = res.data.fetch_k ?? fetchK.value
  } catch (err) { console.error(err) }
}

async function fetchChunks() {
  databaseAppliedFileIdsText.value = databaseFileIdsText.value
  chunks.value = []
  chunksCursor.value = null
  chunksHasMore.value = false
  await fetchNextChunks()
}

async function fetchFiles() {
  files.value = []
  filesCursor.value = null
  filesHasMore.value = false
  await fetchNextFiles()
}

async function fetchIndexJobs() {
  indexJobs.value = []
  indexJobsCursor.value = null
  indexJobsHasMore.value = false
  indexJobsError.value = ''
  await fetchNextIndexJobs()
}

async function fetchNextFiles() {
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

async function fetchNextIndexJobs() {
  if (indexJobsLoading.value) return
  indexJobsLoading.value = true
  try {
    const params = { limit: 50 }
    if (indexJobsCursor.value) params.cursor = indexJobsCursor.value
    const res = await axios.get(`${API}/index/jobs`, { params })
    indexJobs.value = indexJobs.value.concat(res.data.jobs || [])
    indexJobsCursor.value = res.data.next_cursor || null
    indexJobsHasMore.value = Boolean(res.data.has_more)
    indexJobsError.value = ''
  }
  catch (err) {
    indexJobsError.value = err.response?.status === 503 ? t('monitor.indexQueueUnavailable') : (err.response?.data?.detail || err.message)
  }
  finally { indexJobsLoading.value = false }
}

async function deleteFile(file) {
  if (!file?.id || deletingFileId.value) return
  deletingFileId.value = file.id
  uploadMsg.value = { type: 'info', text: t('upload.deletingFile', { name: file.filename }) }
  try {
    const res = await axios.delete(`${API}/files/${encodeURIComponent(file.id)}`)
    uploadMsg.value = { type: 'success', text: t('upload.deletedFile', { name: file.filename, count: res.data.deleted_chunks }) }
    await fetchFiles()
    await fetchChunks()
  } catch (err) {
    uploadMsg.value = { type: 'error', text: `${file.filename}: ${err.response?.data?.detail || err.message}` }
  } finally {
    deletingFileId.value = null
  }
}

async function fetchNextChunks() {
  if (chunksLoading.value) return
  chunksLoading.value = true
  try {
    const params = { limit: 50 }
    if (chunksCursor.value) params.cursor = chunksCursor.value
    const fileIds = parseFileIds(databaseAppliedFileIdsText.value)
    if (fileIds.length) params.file_ids = fileIds.join(',')
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
    fetchNextChunks()
  }
}

function onFilesScroll(event) {
  const el = event.target
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24 && filesHasMore.value) {
    fetchNextFiles()
  }
}

function onIndexJobsScroll(event) {
  const el = event.target
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24 && indexJobsHasMore.value) {
    fetchNextIndexJobs()
  }
}

function onTracesScroll(event) {
  const el = event.target
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24 && tracesHasMore.value) {
    fetchNextTraces()
  }
}

async function fetchMonitor() {
  try {
    const res = await axios.get(`${API}/monitor`)
    monitorState.value = res.data
  } catch (err) { console.error(err) }
}

async function fetchTraces() {
  traces.value = []
  tracesCursor.value = null
  tracesHasMore.value = false
  await fetchNextTraces()
}

async function fetchNextTraces() {
  if (tracesLoading.value) return
  tracesLoading.value = true
  try {
    const params = { limit: 50 }
    if (tracesCursor.value) params.cursor = tracesCursor.value
    const res = await axios.get(`${API}/traces`, { params })
    traces.value = traces.value.concat(res.data.traces || [])
    tracesCursor.value = res.data.next_cursor || null
    tracesHasMore.value = Boolean(res.data.has_more)
  } catch (err) { console.error(err) }
  finally { tracesLoading.value = false }
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

async function startLogStream() {
  stopLogStream()
  logs.value = []
  logStreamController = new AbortController()
  try {
    const response = await fetch(`${API}/logs`, {
      headers: { Authorization: `Bearer ${authToken.value}` },
      signal: logStreamController.signal,
    })
    if (!response.ok || !response.body) return
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) appendLogEvent(part)
    }
  } catch (err) {
    if (err.name !== 'AbortError') console.error(err)
  }
}

function stopLogStream() {
  if (logStreamController) {
    logStreamController.abort()
    logStreamController = null
  }
}

function appendLogEvent(eventText) {
  const line = eventText.split('\n').find(item => item.startsWith('data: '))
  if (!line) return
  const row = JSON.parse(line.slice(6))
  if (logs.value.some(item => item.seq === row.seq)) return
  logs.value = logs.value.concat(row).slice(-300)
  scrollLogsToBottom()
}

function scrollLogsToBottom() {
  nextTick(() => {
    if (logsBox.value) logsBox.value.scrollTop = logsBox.value.scrollHeight
  })
}

function formatLogLine(row) {
  return JSON.stringify(row)
}

async function copyText(value) {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = value
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
}

function searchFileIds() {
  return parseFileIds(fileIdsText.value)
}

function parseFileIds(value) {
  return Array.from(new Set(value.split(',').map(item => item.trim()).filter(Boolean)))
}

function componentModelText(item) {
  if (!item.model) return 'N/A'
  return item.mode ? `${item.model}（${item.mode}）` : item.model
}

function configComponentModel(item) {
  if (!item || item.enable === false) return 'disabled'
  return item.model_name || item.name || item.type || '-'
}

function stageMs(trace, name) {
  const stage = (trace.stages || []).find(item => item.name === name)
  return stage ? ms(stage.elapsed_ms) : '-'
}

function ms(value) {
  if (value === null || value === undefined) return '-'
  return `${Number(value).toFixed(1)}`
}

function jobStatusClass(status) {
  if (status === 'finished') return 'finished'
  if (status === 'failed') return 'failed'
  if (status === 'not_found') return 'missing'
  return 'processing'
}

function jobStatusText(status) {
  return t(`monitor.jobStatus.${jobStatusClass(status)}`)
}

function shortTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
  if (!authToken.value) return
  fetchFiles()
  fetchChunks()
  fetchConfig()
  fetchMonitor()
  if (activeView.value === 'monitor') {
    fetchIndexJobs()
    fetchTraces()
    startMonitorPolling()
  }
})

watch(activeView, value => {
  if (!authToken.value) return
  if (value === 'monitor') {
    fetchIndexJobs()
    fetchTraces()
    startMonitorPolling()
  } else {
    stopMonitorPolling()
  }
})

onUnmounted(() => {
  stopMonitorPolling()
  stopLogStream()
})

function escapeHtml(text) {
  const el = document.createElement('div')
  el.textContent = text
  return el.innerHTML
}

</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif; background: #f5f6fa; color: #1d1d1f; -webkit-font-smoothing: antialiased; }

.app {
  --bg: #f4f6fb;
  --surface: #ffffff;
  --surface-2: #f8fafc;
  --surface-3: #eef3f8;
  --text: #172033;
  --muted: #667085;
  --soft: #98a2b3;
  --border: #dce4ee;
  --border-strong: #b9c7d8;
  --accent: #0f7cff;
  --accent-2: #18a0b5;
  --accent-soft: #e8f2ff;
  --success: #16a071;
  --warning: #d99513;
  --danger: #e65f2b;
  --shadow: 0 18px 55px rgba(40, 56, 85, .10);
  min-height: 100vh;
  max-width: none;
  margin: 0;
  padding: 34px max(32px, calc((100vw - 1180px) / 2));
  background:
    linear-gradient(180deg, rgba(255,255,255,.88), rgba(255,255,255,0) 240px),
    var(--bg);
  color: var(--text);
}

.app.theme-dark {
  --bg: #080c14;
  --surface: #101824;
  --surface-2: #151f2e;
  --surface-3: #1b293b;
  --text: #ecf2ff;
  --muted: #9ba8bd;
  --soft: #748297;
  --border: #26364a;
  --border-strong: #3a506b;
  --accent: #4aa3ff;
  --accent-2: #41d6c3;
  --accent-soft: rgba(74, 163, 255, .14);
  --success: #33c293;
  --warning: #f0b849;
  --danger: #ff7a45;
  --shadow: 0 22px 70px rgba(0, 0, 0, .34);
  background:
    linear-gradient(180deg, rgba(20,31,46,.92), rgba(8,12,20,0) 250px),
    var(--bg);
}

/* Header */
.app-header { margin-bottom: 24px; }
.login-tools { display: flex; justify-content: flex-end; gap: 8px; margin-bottom: 28px; }
.header-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.header-top h1 { font-size: 25px; font-weight: 750; letter-spacing: 0; color: var(--text); }
.header-desc { font-size: 14px; color: var(--muted); margin-top: 7px; max-width: 720px; }
.header-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.switch-group { display: flex; gap: 3px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 3px; box-shadow: 0 8px 26px rgba(16, 36, 62, .06); }
.switch-btn { min-width: 38px; height: 28px; padding: 0 9px; border: none; border-radius: 7px; background: transparent; color: var(--muted); font-size: 12px; font-weight: 600; cursor: pointer; }
.switch-btn.active { background: var(--accent); color: #fff; }
.switch-btn:hover:not(.active) { background: var(--surface-3); color: var(--text); }
.header-logout { height: 36px; padding: 0 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--muted); font-size: 12px; font-weight: 650; cursor: pointer; }
.header-logout:hover { border-color: var(--accent); color: var(--accent); }

.view-tabs { display: flex; gap: 5px; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 5px; margin-bottom: 22px; box-shadow: var(--shadow); width: fit-content; }
.view-tab { min-width: 82px; height: 34px; border: none; border-radius: 10px; background: transparent; color: var(--muted); font-size: 13px; font-weight: 650; cursor: pointer; }
.view-tab.active { background: var(--text); color: var(--surface); }
.app.theme-dark .view-tab.active { background: var(--accent); color: #05111f; }
.view-tab:hover:not(.active) { background: var(--surface-3); color: var(--text); }

/* Login */
.login-view { min-height: 56vh; display: grid; place-items: center; }
.login-card { width: min(420px, 100%); display: grid; gap: 14px; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 26px; box-shadow: var(--shadow); }
.login-card h2 { font-size: 20px; color: var(--text); margin-bottom: 6px; }
.login-card p { font-size: 13px; color: var(--muted); }
.login-card label { display: grid; gap: 6px; font-size: 12px; color: var(--muted); }
.login-card .field-input { width: 100%; height: 38px; }
.login-submit { height: 38px; }

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
.files-head, .file-row { display: grid; grid-template-columns: minmax(220px, 1.2fr) minmax(220px, 1.2fr) minmax(160px, .9fr) 64px 72px; align-items: center; gap: 8px; font-size: 12px; }
.files-head { color: #8e8e93; font-weight: 600; padding: 0 8px 6px; border-bottom: 1px solid #f0f1f4; }
.file-row { min-height: 34px; color: #6c7680; padding: 6px 8px; border-radius: 8px; background: #fff; border: 1px solid #f0f1f4; }
.file-delete { height: 26px; border: 1px solid #ffd6c2; border-radius: 7px; background: #fff7f2; color: #f56a00; font-size: 12px; cursor: pointer; }
.file-delete:hover:not(:disabled) { border-color: #f56a00; background: #fff2e8; }
.file-delete:disabled { color: #c7c7cc; border-color: #e5e5ea; background: #f5f5f7; cursor: not-allowed; }

/* Chunks */
.chunks-card { background: #fff; border-radius: 14px; padding: 20px 24px; margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.04); }
.docs-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.docs-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.docs-head h2 { font-size: 14px; font-weight: 600; color: #1d1d1f; }
.docs-count { font-size: 12px; font-weight: 500; color: #8e8e93; background: #f2f2f5; padding: 0 8px; min-width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; border-radius: 10px; }
.docs-empty { font-size: 13px; color: #aeaeb2; text-align: center; padding: 28px 0; }
.chunk-filter { display: grid; grid-template-columns: 64px minmax(0, 1fr) 64px; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 12px; color: #8e8e93; }
.chunks-scroll { max-height: 420px; overflow: auto; }
.chunks-table { min-width: 1400px; display: grid; gap: 4px; }
.chunks-head, .chunk-row { display: grid; grid-template-columns: minmax(140px, .8fr) minmax(170px, .9fr) minmax(240px, 1.2fr) minmax(120px, .7fr) minmax(150px, .8fr) 92px minmax(260px, 1.5fr); align-items: center; gap: 8px; font-size: 12px; }
.chunks-head { color: #8e8e93; font-weight: 600; padding: 0 8px 6px; border-bottom: 1px solid #f0f1f4; }
.chunk-row { min-height: 34px; color: #6c7680; padding: 6px 8px; border-radius: 8px; background: #fff; border: 1px solid #f0f1f4; }
.copy-cell { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) 38px; align-items: center; gap: 6px; }
.copy-btn { height: 24px; border: 1px solid #e5e5ea; border-radius: 7px; background: #fff; color: #6c7680; font-size: 11px; cursor: pointer; }
.copy-btn:hover { border-color: #409eff; color: #409eff; }
.chunk-id { min-width: 0; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
.ghost-btn.mini { height: 24px; padding: 0 8px; border-radius: 7px; font-size: 11px; }
.ghost-btn:hover { border-color: #409eff; color: #409eff; }
.ghost-btn:disabled { color: #c7c7cc; cursor: not-allowed; }
.ghost-btn:disabled:hover { border-color: #e5e5ea; color: #c7c7cc; }
.monitor-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.monitor-grid + .monitor-block { margin-top: 18px; }
.monitor-section > .monitor-block + .monitor-block { margin-top: 18px; }
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
.trace-list-wrap { max-height: 320px; overflow: auto; }
.trace-table { min-width: 1080px; display: grid; gap: 4px; }
.trace-table-head, .trace-table-row { display: grid; grid-template-columns: minmax(150px, .9fr) minmax(160px, 1.6fr) 90px 46px repeat(8, 72px); align-items: center; gap: 8px; font-size: 12px; }
.trace-table-head { color: #8e8e93; font-weight: 600; padding: 0 8px 6px; border-bottom: 1px solid #f0f1f4; }
.trace-table-row { min-height: 32px; color: #6c7680; padding: 6px 8px; border-radius: 8px; background: #fff; border: 1px solid #f0f1f4; }
.trace-table-row strong { color: #409eff; font-weight: 600; }
.trace-query { color: #1d1d1f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-empty { font-size: 12px; color: #aeaeb2; padding: 18px 0; text-align: center; }
.error-text { color: #f56a00; }
.logs-box { height: 520px; overflow: auto; margin: 0; border: 1px solid #e5e5ea; border-radius: 9px; background: #0f1720; color: #d8e2ee; padding: 12px; font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; word-break: break-word; }
.job-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.job-filters { display: flex; flex-wrap: wrap; gap: 4px; }
.job-filter { height: 24px; padding: 0 8px; border: 1px solid #e5e5ea; border-radius: 7px; background: #fff; color: #6c7680; font-size: 11px; cursor: pointer; }
.job-filter.active { border-color: #409eff; color: #409eff; background: #e6f2ff; }
.job-table-wrap { max-height: 320px; overflow: auto; }
.job-table { min-width: 1320px; display: grid; gap: 4px; }
.job-table-head, .job-table-row { display: grid; grid-template-columns: 82px minmax(170px, 1fr) minmax(150px, 1fr) minmax(170px, 1fr) 58px minmax(240px, 1.4fr) minmax(160px, 1fr) minmax(160px, 1fr); align-items: center; gap: 8px; font-size: 12px; }
.job-table-head { color: #8e8e93; font-weight: 600; padding: 0 8px 6px; border-bottom: 1px solid #f0f1f4; }
.job-table-row { min-height: 32px; color: #6c7680; padding: 6px 8px; border-radius: 8px; background: #fff; border: 1px solid #f0f1f4; }
.job-status { font-weight: 600; }
.job-status.processing { color: #d99513; }
.job-status.finished { color: #22a67e; }
.job-status.failed { color: #f56a00; }
.job-status.missing { color: #8e8e93; }
.job-error { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #f56a00; }

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

.upload-card,
.files-card,
.chunks-card,
.monitor-section,
.search-section,
.results-section {
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}

.upload-zone {
  background: var(--surface-2);
  border-color: var(--border-strong);
  color: var(--text);
}
.upload-zone:hover { border-color: var(--accent); background: var(--accent-soft); }
.upload-icon { color: var(--accent); }
.upload-title,
.docs-head h2,
.monitor-head h2,
.results-count,
.trace-query,
.chunk-content,
.header-top h1,
.component-row strong,
.kv-list strong,
.metric-row strong {
  color: var(--text);
}
.upload-hint,
.docs-count,
.docs-empty,
.docs-loading,
.results-mode,
.results-balance,
.results-elapsed,
.monitor-head p,
.block-title,
.component-row,
.component-name,
.kv-list div,
.metric-row span,
.scope-title,
.topk-label,
.cand-label,
.rerank-control,
.bal-label,
.chunk-filter,
.no-results p,
.no-results-hint,
.trace-empty {
  color: var(--muted);
}

.primary-btn,
.search-btn {
  background: var(--accent);
  color: #fff;
  box-shadow: 0 10px 22px rgba(15, 124, 255, .22);
}
.primary-btn:hover:not(:disabled),
.search-btn:hover:not(:disabled) { background: #0869dc; }
.primary-btn:disabled,
.search-btn:disabled { background: var(--border-strong); box-shadow: none; }
.app.theme-dark .primary-btn:hover:not(:disabled),
.app.theme-dark .search-btn:hover:not(:disabled) { background: #66b4ff; color: #06111d; }

.monitor-block,
.metric-row div,
.files-head,
.file-row,
.chunks-head,
.chunk-row,
.trace-table-head,
.trace-table-row,
.job-table-head,
.job-table-row,
.mode-tabs,
.field-input,
.field-select,
.search-input,
.topk-select,
.cand-input,
.ghost-btn,
.copy-btn,
.job-filter,
.docs-more {
  background: var(--surface-2);
  border-color: var(--border);
  color: var(--text);
}
.files-head,
.chunks-head,
.trace-table-head,
.job-table-head {
  color: var(--muted);
}
.file-row,
.chunk-row,
.trace-table-row,
.job-table-row {
  background: var(--surface);
  color: var(--muted);
}
.field-input::placeholder,
.search-input::placeholder { color: var(--soft); }
.field-input:focus,
.field-select:focus,
.search-input:focus,
.cand-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.mode-tab { color: var(--muted); }
.mode-tab.active { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.mode-tab:hover:not(.active) { color: var(--text); }
.bal-slider,
.rerank-checkbox { accent-color: var(--accent); }
.bal-value,
.trace-table-row strong { color: var(--accent); }
.logs-box { border-color: var(--border); background: #0f1720; color: #d8e2ee; }
.app.theme-dark .logs-box { background: #050b13; color: #d6e4f2; }
.job-filter.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.job-status.processing { color: var(--warning); }
.job-status.finished { color: var(--success); }
.job-status.failed,
.job-error { color: var(--danger); }
.job-status.missing { color: var(--soft); }
.results-bar,
.result-card,
.files-head,
.chunks-head,
.trace-table-head,
.job-table-head { border-color: var(--border); }
.result-body { color: var(--text); }
.result-file { color: var(--muted); }
.result-file svg { stroke: var(--muted); }
.upload-feedback.info { color: var(--accent); background: var(--accent-soft); }
.upload-feedback.success { color: var(--success); background: rgba(34,166,126,.12); }
.upload-feedback.error { color: var(--danger); background: rgba(245,106,0,.12); }
.file-delete { border-color: rgba(245,106,0,.32); background: rgba(245,106,0,.08); color: var(--danger); }
.file-delete:hover:not(:disabled) { border-color: var(--danger); background: rgba(245,106,0,.14); }
.file-delete:disabled { color: var(--soft); border-color: var(--border); background: var(--surface-3); }
.docs-more:hover,
.ghost-btn:hover { border-color: var(--accent); color: var(--accent); }
.copy-btn:hover { border-color: var(--accent); color: var(--accent); }
.docs-count { background: var(--surface-3); }
.status-dot.ready { background: var(--success); }
.status-dot.loading { background: var(--warning); }
.status-dot.disabled { background: var(--soft); }
.status-dot.error { background: var(--danger); }

@media (max-width: 760px) {
  .app { padding: 24px 16px; }
  .header-top { flex-direction: column; }
  .header-actions { justify-content: flex-start; }
  .view-tabs { width: 100%; overflow-x: auto; }
  .view-tab { min-width: 76px; }
  .monitor-grid,
  .database-grid,
  .config-grid { grid-template-columns: 1fr; }
  .search-input-wrap { flex-direction: column; }
  .search-btn { height: 38px; }
  .results-bar { flex-wrap: wrap; gap: 8px 12px; }
}
</style>
