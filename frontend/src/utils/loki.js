import { nextTick, ref } from 'vue'
import axios from './api'
import { useAuthStore } from '../stores/auth'

const LOG_LIMIT = 500

export const logs = ref([])
export const logsBox = ref(null)

let source = null
let currentFilter = { nodeId: '', container: 'rag-backend' }

export async function fetchLabelValues(label) {
  const res = await axios.get(`/api/logs/labels/${label}`)
  return res.data?.values || []
}

export async function startLogsTail(filter = {}) {
  stopLogsTail()
  currentFilter = {
    nodeId: filter.nodeId || '',
    container: filter.container || 'rag-backend',
  }
  logs.value = []
  const token = useAuthStore().authToken
  const params = new URLSearchParams()
  params.set('token', token)
  if (currentFilter.nodeId) params.set('node_id', currentFilter.nodeId)
  if (currentFilter.container) params.set('container', currentFilter.container)
  source = new EventSource(`/api/logs/stream?${params.toString()}`)
  source.onmessage = event => {
    appendRows(JSON.parse(event.data))
  }
}

export function stopLogsTail() {
  if (source) {
    source.close()
    source = null
  }
}

export function formatLogLine(row) {
  const parsed = row.parsed
  if (!parsed) return row.line
  const pieces = [
    parsed.time || row.time || '',
    parsed.level || '',
    parsed.logger || '',
    parsed.event || '',
    parsed.message || row.line,
  ].filter(Boolean)
  return pieces.join(' ')
}

function appendRows(rows) {
  if (!rows.length) return
  logs.value = [...logs.value, ...rows].slice(-LOG_LIMIT)
  nextTick(() => {
    if (logsBox.value) logsBox.value.scrollTop = logsBox.value.scrollHeight
  })
}
