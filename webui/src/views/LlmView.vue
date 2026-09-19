<template>
  <main class="llm-view">
    <div class="page-head">
      <div>
        <h2>{{ t('llm.title') }}</h2>
        <p>{{ t('llm.desc') }}</p>
      </div>
    </div>

    <div v-if="!currentApp" class="trace-empty">{{ t('upload.selectApp') }}</div>
    <template v-else>
      <div class="llm-toolbar">
        <div>
          <p>{{ t('llm.thread') }}: <span class="thread-id">{{ threadId }}</span></p>
        </div>
        <el-button @click="newConversation">{{ t('llm.newConversation') }}</el-button>
      </div>

      <div class="llm-chat">
        <div v-if="messages.length === 0" class="llm-empty">{{ t('llm.empty') }}</div>
        <div v-for="(message, index) in messages" :key="index" class="llm-message" :class="message.role">
          <div class="llm-role">{{ message.role === 'user' ? t('llm.user') : t('llm.assistant') }}</div>
          <div class="llm-bubble">{{ message.content }}</div>
        </div>
      </div>

      <form class="llm-input" @submit.prevent="sendMessage">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          maxlength="2000"
          show-word-limit
          :placeholder="t('llm.placeholder')"
          @keydown.enter.exact.prevent="sendMessage"
        />
        <el-button type="primary" native-type="submit" :loading="streaming" :disabled="!input.trim() || streaming">
          {{ streaming ? t('llm.responding') : t('llm.send') }}
        </el-button>
      </form>
    </template>
  </main>
</template>

<script setup>
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useAppsStore } from '../stores/apps'
import { useLlmChatStore } from '../stores/llmChat'
import { errorMessage, indexErrorMessage, showToast } from '../utils/toast'

const API_PATH = '/api/v1/llm/chat/stream'
const { t } = useI18n()
const route = useRoute()
const appsStore = useAppsStore()
const llmChatStore = useLlmChatStore()
const { apps } = storeToRefs(appsStore)

const currentAppId = computed(() => route.params.app_id)
const currentApp = computed(() => apps.value.find(app => app.app_id === currentAppId.value))
const session = computed(() => llmChatStore.sessionFor(currentAppId.value))
const threadId = computed(() => session.value.threadId)
const messages = computed(() => session.value.messages)
const input = ref('')
const streaming = ref(false)

function newConversation() {
  llmChatStore.newConversation(currentAppId.value)
}

async function requestHeaders() {
  const app = currentApp.value
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${app.api_key}`,
  }
}

async function sendMessage() {
  const content = input.value.trim()
  if (!content || streaming.value || !currentApp.value) return

  input.value = ''
  messages.value.push({ role: 'user', content })
  messages.value.push({ role: 'assistant', content: '' })
  const assistantIndex = messages.value.length - 1
  streaming.value = true

  const body = JSON.stringify({ thread_id: threadId.value, message: content })
  try {
    const res = await fetch(API_PATH, {
      method: 'POST',
      headers: await requestHeaders(),
      body,
    })
    if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status} ${res.statusText}`)
    await readStream(res, assistantIndex)
  } catch (err) {
    messages.value[assistantIndex].content = errorMessage(err, t('llm.requestFailed'))
    showToast('error', messages.value[assistantIndex].content)
  } finally {
    streaming.value = false
  }
}

async function readStream(res, assistantIndex) {
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''
      for (const eventText of events) handleEvent(eventText, assistantIndex)
    }
    if (buffer) handleEvent(buffer, assistantIndex)
  } finally {
    try {
      await reader.cancel()
    } finally {
      reader.releaseLock()
    }
  }
}

function handleEvent(eventText, assistantIndex) {
  const line = eventText.split('\n').find(item => item.startsWith('data:'))
  if (!line) return
  const event = JSON.parse(line.slice(5).trim())
  if (event.type === 'token') messages.value[assistantIndex].content += event.content || ''
  if (event.type === 'error') throw new Error(indexErrorMessage(event))
}
</script>

<style scoped>
.llm-view { display: grid; grid-template-rows: auto auto minmax(360px, 1fr) auto; gap: 16px; min-height: calc(100vh - 142px); }
.llm-toolbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.llm-toolbar p { font-size: 12px; color: var(--el-text-color-secondary); }
.thread-id { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color: var(--el-text-color-primary); }
.llm-chat { min-height: 360px; overflow: auto; border: 1px solid var(--el-border-color); border-radius: 6px; padding: 16px; background: var(--el-bg-color); }
.llm-empty { height: 100%; min-height: 320px; display: grid; place-items: center; color: var(--el-text-color-secondary); font-size: 13px; }
.llm-message { display: grid; gap: 6px; margin-bottom: 16px; }
.llm-message.user { justify-items: end; }
.llm-message.assistant { justify-items: start; }
.llm-role { font-size: 12px; color: var(--el-text-color-secondary); }
.llm-bubble { max-width: min(760px, 82%); white-space: pre-wrap; word-break: break-word; line-height: 1.6; padding: 10px 12px; border-radius: 6px; border: 1px solid var(--el-border-color); background: var(--el-fill-color-light); }
.llm-message.user .llm-bubble { color: #fff; background: var(--el-color-primary); border-color: var(--el-color-primary); }
.llm-input { display: grid; grid-template-columns: minmax(0, 1fr) 96px; align-items: stretch; gap: 10px; }
.llm-input .el-button { height: auto; }
@media (max-width: 720px) {
  .llm-toolbar { display: grid; }
  .llm-input { grid-template-columns: 1fr; }
  .llm-bubble { max-width: 100%; }
}
</style>
