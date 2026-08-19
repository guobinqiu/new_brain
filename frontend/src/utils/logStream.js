import { ref, nextTick } from 'vue'

const API = '/api'

export const logs = ref([])
export const logsBox = ref(null)

let logStreamController = null

export async function startLogStream() {
  stopLogStream()
  logs.value = []
  logStreamController = new AbortController()
  try {
    const token = localStorage.getItem('rag_token') || ''
    const response = await fetch(`${API}/logs`, {
      headers: { Authorization: `Bearer ${token}` },
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

export function stopLogStream() {
  if (logStreamController) {
    logStreamController.abort()
    logStreamController = null
  }
}

function appendLogEvent(eventText) {
  const line = eventText.split('\n').find(item => item.startsWith('data: '))
  if (!line) return
  let row
  try {
    row = JSON.parse(line.slice(6))
  } catch (err) {
    logs.value = logs.value.concat({ msg: line.slice(6), raw: true }).slice(-300)
    scrollLogsToBottom()
    return
  }
  if (logs.value.some(item => item.seq === row.seq)) return
  logs.value = logs.value.concat(row).slice(-300)
  scrollLogsToBottom()
}

function scrollLogsToBottom() {
  nextTick(() => {
    if (logsBox.value) logsBox.value.scrollTop = logsBox.value.scrollHeight
  })
}

export function formatLogLine(row) {
  return JSON.stringify(row)
}
