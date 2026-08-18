<template>
  <main class="logs-view">
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
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { logs, logsBox, formatLogLine, startLogStream, stopLogStream } from '../utils/logStream'

const { t } = useI18n()

onMounted(startLogStream)
onUnmounted(stopLogStream)
</script>
