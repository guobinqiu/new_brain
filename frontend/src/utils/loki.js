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
  const res = await axios.get(`/loki/label/${label}/values`)
  return res.data?.data || []
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
  const res = await axios.get('/loki/query_range', {
    params: {
      query: logQuery(),
      start: startNs.toString(),
      end: nowNs.toString(),
      limit: 500,
      direction: initial ? 'backward' : 'forward',
    },
  })
  const rows = parseStreams(res.data?.data?.result || [])
  if (initial) rows.reverse()
  appendRows(rows)
}

function logQuery() {
  const labels = []
  if (currentFilter.nodeId) labels.push(`node_id="${escapeLabel(currentFilter.nodeId)}"`)
  if (currentFilter.container) labels.push(`container="${escapeLabel(currentFilter.container)}"`)
  return `{${labels.join(',')}}`
}

function escapeLabel(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}

function parseStreams(streams) {
  const rows = []
  for (const stream of streams) {
    for (const [ts, line] of stream.values || []) {
      rows.push({ ts, time: formatTimestamp(ts), line, parsed: parseJson(line) })
    }
  }
  return rows.sort((a, b) => Number(BigInt(a.ts) - BigInt(b.ts)))
}

function parseJson(line) {
  try {
    return JSON.parse(line)
  } catch {
    return null
  }
}

function formatTimestamp(ts) {
  return new Date(Number(BigInt(ts) / 1000000n)).toLocaleString()
}

function appendRows(rows) {
  if (!rows.length) return
  lastTimestampNs = rows[rows.length - 1].ts
  logs.value = [...logs.value, ...rows].slice(-LOG_LIMIT)
  nextTick(() => {
    if (logsBox.value) logsBox.value.scrollTop = logsBox.value.scrollHeight
  })
}
