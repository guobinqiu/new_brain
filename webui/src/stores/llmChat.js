import { defineStore } from 'pinia'
import { reactive } from 'vue'

function newThreadId() {
  const bytes = new Uint8Array(8)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

export const useLlmChatStore = defineStore('llmChat', () => {
  const sessions = reactive({})

  function sessionFor(appId) {
    const key = appId || 'default'
    if (!sessions[key]) {
      sessions[key] = {
        threadId: newThreadId(),
        messages: [],
      }
    }
    return sessions[key]
  }

  function newConversation(appId) {
    const session = sessionFor(appId)
    session.threadId = newThreadId()
    session.messages = []
  }

  return { sessions, sessionFor, newConversation }
})
