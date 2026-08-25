import axios from './api'

const LOG_LIMIT = 500

export async function fetchLabelValues(label) {
  const res = await axios.get(`/api/logs/labels/${label}`)
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
  if (filter.end != null) params.set('end', String(filter.end))
  const res = await axios.get(`/api/logs?${params.toString()}`)
  return res.data || { logs: [], has_more: false, next_end: null }
}

export function formatLogLine(row) {
  const parsed = row.parsed
  if (!parsed) return row.line
  const pieces = [
    parsed.time || row.time || '',
    row.container || '',
    parsed.level || '',
    parsed.logger || '',
    parsed.event || '',
    parsed.message || row.line,
  ].filter(Boolean)
  return pieces.join(' ')
}

export { LOG_LIMIT }
