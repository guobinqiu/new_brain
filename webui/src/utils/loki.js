import axios from './api'
import { shortTime } from './format'

const LOG_LIMIT = 500

export async function fetchLabelValues(label, range = null) {
  const params = new URLSearchParams()
  if (range?.length === 2) {
    params.set('start', String(range[0]))
    params.set('end', String(range[1]))
  }
  const query = params.toString()
  const res = await axios.get(`/api/rag/logs/labels/${label}${query ? `?${query}` : ''}`)
  return res.data?.values || []
}

export async function fetchLogs(filter = {}) {
  const params = new URLSearchParams()
  params.set('limit', String(LOG_LIMIT))
  if (filter.nodeId) params.set('node_id', filter.nodeId)
  if (filter.container) params.set('container', filter.container)
  if (filter.range?.length === 2) {
    params.set('start', String(filter.range[0]))
    params.set('end', String(filter.range[1]))
  }
  if (filter.start != null) params.set('start', String(filter.start))
  const res = await axios.get(`/api/rag/logs?${params.toString()}`)
  return res.data || { logs: [], has_more: false, next_start: null }
}

export function formatLogLine(row) {
  const parsed = row.parsed
  if (!parsed) return row.line
  const time = parsed.time || row.time
  const pieces = [
    time ? shortTime(time) : '',
    row.container || '',
    parsed.level || '',
    parsed.logger || '',
    parsed.event || '',
    parsed.message || row.line,
  ].filter(Boolean)
  return pieces.join(' ')
}

export { LOG_LIMIT }
