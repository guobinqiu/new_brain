import { nextTick, ref } from 'vue'
import axios from './api'

const LOG_LIMIT = 2000
const INITIAL_WINDOW_MS = 15 * 60 * 1000
const POLL_INTERVAL_MS = 2000

export const logs = ref([])
export const logsBox = ref(null)

let timer = null
let lastTimestampNs = null
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
  lastTimestampNs = null
  await fetchLogs({ initial: true })
  timer = window.setInterval(() => {
    fetchLogs({ initial: false })
  }, POLL_INTERVAL_MS)
}

export function stopLogsTail() {
  if (timer) {
    window.clearInterval(timer)
    timer = null
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

async function fetchLogs({ initial }) {
  const nowNs = BigInt(Date.now()) * 1000000n
  const startNs = initial
    ? BigInt(Date.now() - INITIAL_WINDOW_MS) * 1000000n
    : BigInt(lastTimestampNs || nowNs) + 1n
  const res = await axios.get('/api/logs', {
    params: {
      node_id: currentFilter.nodeId || undefined,
      container: currentFilter.container || undefined,
      start: startNs.toString(),
      end: nowNs.toString(),
      limit: 500,
      direction: initial ? 'backward' : 'forward',
    },
  })
  const rows = res.data?.logs || []
  if (initial) rows.reverse()
  appendRows(rows)
}

function appendRows(rows) {
  if (!rows.length) return
  lastTimestampNs = rows[rows.length - 1].ts
  logs.value = [...logs.value, ...rows].slice(-LOG_LIMIT)
  nextTick(() => {
    if (logsBox.value) logsBox.value.scrollTop = logsBox.value.scrollHeight
  })
}
