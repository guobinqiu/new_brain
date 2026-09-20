<template>
  <main class="ops-view">
    <section class="ops-section">
      <div class="page-head">
        <div>
          <h2>{{ t(`ops.tabs.${tab}`) }}</h2>
          <p>{{ t('ops.desc') }}</p>
        </div>
        <div class="ops-actions">
          <el-button size="small" @click="fetchAll">{{ t('common.refresh') }}</el-button>
        </div>
      </div>

        <template v-if="tab === 'deploy'">
          <div class="config-layout">
            <aside class="config-list">
              <el-button
                v-for="item in deployConfigs"
                :key="item.name"
                :type="selectedConfig === item.name ? 'primary' : 'default'"
                plain
                @click="selectConfig(item.name)"
              >
                {{ configLabel(item) }}
              </el-button>
            </aside>
            <section class="config-editor">
              <div class="editor-head">
                <div>
                  <h3>{{ configLabel(currentConfig) }}</h3>
                  <p>{{ currentConfig?.path || '' }}</p>
                </div>
                <div class="editor-actions">
                  <el-button v-if="deployTarget" size="small" type="primary" :loading="configAction === 'deploy'" @click="publishStack">{{ t('ops.actions.publish') }}</el-button>
                </div>
              </div>
              <el-input v-model="configContent" type="textarea" :rows="26" spellcheck="false" />
              <div class="editor-foot">
                <p class="config-note">{{ t('ops.deployNote') }}</p>
                <div class="editor-footer-actions">
                  <el-button size="small" :loading="configAction === 'validate'" @click="validateConfig">{{ t('ops.actions.validate') }}</el-button>
                  <el-button size="small" :loading="configAction === 'save'" @click="saveConfig">{{ t('ops.actions.save') }}</el-button>
                </div>
              </div>
            </section>
          </div>
        </template>

        <template v-if="tab === 'services'">
          <el-tabs v-model="serviceTab">
            <el-tab-pane :label="t('ops.tabs.controlServices')" name="control">
              <el-table :data="controlServices" stripe>
                <el-table-column prop="name" :label="t('ops.columns.service')" min-width="180" />
                <el-table-column prop="image" :label="t('ops.columns.image')" min-width="260" show-overflow-tooltip />
                <el-table-column :label="t('ops.columns.replicas')" width="110">
                  <template #default="{ row }">{{ row.running ?? '-' }} / {{ row.desired ?? '-' }}</template>
                </el-table-column>
                <el-table-column :label="t('ops.columns.ports')" min-width="140">
                  <template #default="{ row }">{{ portsText(row.ports) }}</template>
                </el-table-column>
                <el-table-column :label="t('ops.columns.actions')" width="100" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" :loading="serviceLogLoading === row.name" @click="loadServiceLogs(row.name)">{{ t('ops.actions.logs') }}</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane :label="t('ops.tabs.appServices')" name="app">
              <el-table :data="appServices" stripe>
                <el-table-column prop="name" :label="t('ops.columns.service')" min-width="180" />
                <el-table-column prop="image" :label="t('ops.columns.image')" min-width="260" show-overflow-tooltip />
                <el-table-column :label="t('ops.columns.replicas')" width="110">
                  <template #default="{ row }">{{ row.running ?? '-' }} / {{ row.desired ?? '-' }}</template>
                </el-table-column>
                <el-table-column :label="t('ops.columns.ports')" min-width="140">
                  <template #default="{ row }">{{ portsText(row.ports) }}</template>
                </el-table-column>
                <el-table-column :label="t('ops.columns.actions')" width="400" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" :loading="serviceLogLoading === row.name" :disabled="serviceBusy(row.name)" @click="loadServiceLogs(row.name)">{{ t('ops.actions.logs') }}</el-button>
                    <el-button size="small" :loading="serviceActionKey === `${row.name}:start`" :disabled="serviceBusy(row.name)" @click="serviceAction(row.name, 'start')">{{ t('ops.actions.start') }}</el-button>
                    <el-button size="small" :loading="serviceActionKey === `${row.name}:stop`" :disabled="serviceBusy(row.name)" @click="serviceAction(row.name, 'stop')">{{ t('ops.actions.stop') }}</el-button>
                    <el-button size="small" :loading="serviceActionKey === `${row.name}:rollout`" :disabled="serviceBusy(row.name)" @click="serviceAction(row.name, 'rollout')">{{ t('ops.actions.rollout') }}</el-button>
                    <el-button v-if="canScaleService(row.name)" size="small" :loading="scalingService === row.name" :disabled="serviceBusy(row.name)" @click="scaleService(row)">{{ t('ops.actions.scale') }}</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane :label="t('ops.tabs.infraServices')" name="infra">
              <el-table :data="infraServices" stripe>
                <el-table-column prop="name" :label="t('ops.columns.service')" min-width="180" />
                <el-table-column prop="image" :label="t('ops.columns.image')" min-width="260" show-overflow-tooltip />
                <el-table-column :label="t('ops.columns.replicas')" width="110">
                  <template #default="{ row }">{{ row.running ?? '-' }} / {{ row.desired ?? '-' }}</template>
                </el-table-column>
                <el-table-column :label="t('ops.columns.ports')" min-width="140">
                  <template #default="{ row }">{{ portsText(row.ports) }}</template>
                </el-table-column>
                <el-table-column :label="t('ops.columns.actions')" width="260" fixed="right">
                  <template #default="{ row }">
                    <div class="service-actions">
                      <el-button size="small" :loading="serviceLogLoading === row.name" :disabled="serviceBusy(row.name)" @click="loadServiceLogs(row.name)">{{ t('ops.actions.logs') }}</el-button>
                      <el-button size="small" :loading="serviceActionKey === `${row.name}:start`" :disabled="serviceBusy(row.name)" @click="serviceAction(row.name, 'start')">{{ t('ops.actions.start') }}</el-button>
                      <el-button size="small" :loading="serviceActionKey === `${row.name}:stop`" :disabled="serviceBusy(row.name)" @click="serviceAction(row.name, 'stop')">{{ t('ops.actions.stop') }}</el-button>
                    </div>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </template>

        <template v-if="tab === 'configs'">
          <div class="config-layout">
            <aside class="config-list">
              <el-button
                v-for="item in serviceConfigs"
                :key="item.name"
                :type="selectedConfig === item.name ? 'primary' : 'default'"
                plain
                @click="selectConfig(item.name)"
              >
                {{ configLabel(item) }}
              </el-button>
            </aside>
            <section class="config-editor">
              <div class="editor-head">
                <div>
                  <h3>{{ configLabel(currentConfig) }}</h3>
                  <p>{{ currentConfig?.path || '' }}</p>
                </div>
                <div class="editor-actions">
                  <el-button size="small" type="primary" :loading="configAction === 'apply'" @click="applyConfig">{{ t('ops.actions.apply') }}</el-button>
                </div>
              </div>
              <el-input v-model="configContent" type="textarea" :rows="26" spellcheck="false" />
              <div class="editor-foot">
                <p class="config-note">{{ t('ops.configNote') }}</p>
                <div class="editor-footer-actions">
                  <el-button size="small" :loading="configAction === 'validate'" @click="validateConfig">{{ t('ops.actions.validate') }}</el-button>
                  <el-button size="small" :loading="configAction === 'save'" @click="saveConfig">{{ t('ops.actions.save') }}</el-button>
                </div>
              </div>
            </section>
          </div>
        </template>

        <template v-if="tab === 'nodes'">
          <p class="ops-note">{{ t('ops.nodesNote') }}</p>
          <div class="join-tools">
            <el-button size="small" @click="fetchJoinCommand('worker')">{{ t('ops.actions.workerJoin') }}</el-button>
            <el-button size="small" @click="fetchJoinCommand('manager')">{{ t('ops.actions.managerJoin') }}</el-button>
          </div>
          <el-input v-if="joinCommand" v-model="joinCommand" readonly class="join-command" />
          <el-table :data="nodes" stripe>
            <el-table-column prop="hostname" :label="t('ops.columns.node')" min-width="160" />
            <el-table-column prop="role" :label="t('ops.columns.role')" width="110" />
            <el-table-column prop="state" :label="t('ops.columns.state')" width="110" />
            <el-table-column prop="availability" :label="t('ops.columns.availability')" width="110" />
            <el-table-column prop="addr" :label="t('ops.columns.addr')" min-width="160" />
            <el-table-column :label="t('ops.columns.leader')" width="90">
              <template #default="{ row }">{{ Boolean(row.leader) }}</template>
            </el-table-column>
          </el-table>
        </template>
    </section>
    <el-dialog v-model="scaleDialogVisible" :title="t('ops.actions.scale')" width="360px">
      <div class="scale-dialog">
        <el-input-number v-model="scaleTarget.replicas" :min="0" :step="1" :precision="0" />
      </div>
      <template #footer>
        <el-button @click="scaleDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="scalingService === scaleTarget.service" @click="submitScale">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="logsDialogVisible" :title="`${t('ops.actions.logs')} ${logsService}`" width="960px">
      <pre v-if="serviceLogs" class="logs-box ops-service-logs">{{ serviceLogs }}</pre>
      <div v-else class="trace-empty">{{ t('ops.emptyLogs') }}</div>
      <template #footer>
        <el-button @click="logsDialogVisible = false">{{ t('common.close') }}</el-button>
      </template>
    </el-dialog>
  </main>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'
import { confirmBox } from '../utils/messageBox'
import { errorMessage, showToast } from '../utils/toast'

const { t } = useI18n()
const props = defineProps({ section: { type: String, required: true } })
const tab = computed(() => props.section)
const serviceTab = ref('app')
const services = ref([])
const nodes = ref([])
const configs = ref([])
const selectedConfig = ref('')
const configContent = ref('')
const joinCommand = ref('')
const configAction = ref('')
const serviceActionKey = ref('')
const scalingService = ref('')
const serviceLogLoading = ref('')
const scaleDialogVisible = ref(false)
const scaleTarget = ref({ service: '', replicas: 0 })
const logsDialogVisible = ref(false)
const logsService = ref('')
const serviceLogs = ref('')

const currentConfig = computed(() => configs.value.find(item => item.name === selectedConfig.value))
const deployTarget = computed(() => ({ deploy: 'app', infra: 'infra' })[selectedConfig.value])
const deployConfigs = computed(() => configs.value.filter(item => item.requires_deploy))
const serviceConfigs = computed(() => configs.value.filter(item => !item.requires_deploy))
const controlServices = computed(() => services.value.filter(item => item.group === 'ctrl'))
const appServices = computed(() => services.value.filter(item => item.group === 'app'))
const infraServices = computed(() => services.value.filter(item => item.group === 'infra'))

function portsText(ports) {
  if (!Array.isArray(ports) || ports.length === 0) return '-'
  return ports.map(port => `${port.PublishedPort || '-'}:${port.TargetPort || '-'}`).join(', ')
}

function configLabel(item) {
  if (!item) return '-'
  if (item.name === 'env') return t('ops.environment')
  if (item.name === 'deploy') return t('ops.tabs.appServices')
  if (item.name === 'infra') return t('ops.tabs.infraServices')
  return item.requires_deploy ? item.path : item.service || item.name
}

function canScaleService(service) {
  return services.value.some(item => item.name === service && item.group === 'app')
}

function serviceBusy(service) {
  return scalingService.value === service || serviceActionKey.value.startsWith(`${service}:`)
}

async function paintLoading() {
  await nextTick()
  await new Promise(resolve => requestAnimationFrame(resolve))
}

async function fetchAll() {
  if (tab.value === 'services') return fetchServices()
  if (tab.value === 'nodes') return fetchNodes()
  await fetchConfigs()
}

async function fetchServices() {
  try {
    const res = await axios.get('/api/ops/services')
    services.value = res.data?.services || []
  } catch (err) { showToast('error', errorMessage(err)) }
}

async function fetchNodes() {
  try {
    const res = await axios.get('/api/ops/nodes')
    nodes.value = res.data?.nodes || []
  } catch (err) { showToast('error', errorMessage(err)) }
}

async function fetchConfigs() {
  try {
    const res = await axios.get('/api/ops/configs')
    configs.value = res.data?.configs || []
    await ensureSelectedConfig()
  } catch (err) { showToast('error', errorMessage(err)) }
}

async function ensureSelectedConfig() {
  const activeConfigs = tab.value === 'deploy' ? deployConfigs.value : serviceConfigs.value
  if (activeConfigs.some(item => item.name === selectedConfig.value)) return selectConfig(selectedConfig.value)
  if (activeConfigs.length > 0) await selectConfig(activeConfigs[0].name)
}

async function selectConfig(name) {
  selectedConfig.value = name
  try {
    const res = await axios.get(`/api/ops/configs/${name}`)
    configContent.value = res.data?.content || ''
  } catch (err) { showToast('error', errorMessage(err)) }
}

async function validateConfig() {
  if (!selectedConfig.value) return
  configAction.value = 'validate'
  try {
    await axios.post(`/api/ops/configs/${selectedConfig.value}/validate`, { content: configContent.value })
    showToast('success', t('ops.validateOk'))
  } catch (err) { showToast('error', errorMessage(err)) } finally { configAction.value = '' }
}

async function saveConfig() {
  if (!selectedConfig.value) return
  configAction.value = 'save'
  try {
    const res = await axios.put(`/api/ops/configs/${selectedConfig.value}`, { content: configContent.value })
    configContent.value = res.data?.content || configContent.value
    showToast('success', t('ops.savedConfig'))
  } catch (err) { showToast('error', errorMessage(err)) } finally { configAction.value = '' }
}

async function applyConfig() {
  if (!selectedConfig.value) return
  try {
    await confirmBox(t, t('ops.applyConfirm', { name: selectedConfig.value }), t('ops.actions.apply'), { type: 'warning' })
  } catch {
    return
  }
  configAction.value = 'apply'
  try {
    const res = await axios.post('/api/ops/configs/apply', { name: selectedConfig.value })
    showToast('success', res.data?.deploy ? t('ops.applied') : t('ops.appliedConfig', { service: res.data?.service || selectedConfig.value }))
    await fetchServices()
  } catch (err) { showToast('error', errorMessage(err)) } finally { configAction.value = '' }
}

async function publishStack() {
  const target = deployTarget.value
  if (!target) return
  const name = configLabel(currentConfig.value)
  try {
    await confirmBox(t, t('ops.publishConfirm', { name }), t('ops.actions.publish'), { type: 'warning' })
  } catch {
    return
  }
  configAction.value = 'deploy'
  try {
    await axios.post('/api/ops/stack/deploy', null, { params: { target } })
    showToast('success', t('ops.published', { name }))
    await fetchServices()
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    configAction.value = ''
  }
}

async function serviceAction(service, action) {
  serviceActionKey.value = `${service}:${action}`
  try {
    await paintLoading()
    await axios.post(`/api/ops/services/${service}/${action}`)
    showToast('success', t('ops.submitted', { service, action }))
    await fetchServices()
  } catch (err) { showToast('error', errorMessage(err)) } finally { serviceActionKey.value = '' }
}

function scaleService(row) {
  const service = row.name
  const currentReplicas = Number(row.desired ?? row.running ?? 0)
  scaleTarget.value = { service, replicas: currentReplicas }
  scaleDialogVisible.value = true
}

async function submitScale() {
  const service = scaleTarget.value.service
  const replicas = Number(scaleTarget.value.replicas)
  scalingService.value = service
  try {
    await paintLoading()
    await axios.post('/api/ops/services/scale', { service, replicas })
    showToast('success', t('ops.scaled', { service, replicas }))
    scaleDialogVisible.value = false
    await fetchServices()
  } catch (err) { showToast('error', errorMessage(err)) } finally { scalingService.value = '' }
}

async function loadServiceLogs(service) {
  serviceLogLoading.value = service
  logsService.value = service
  serviceLogs.value = ''
  try {
    const res = await axios.get(`/api/ops/services/${encodeURIComponent(service)}/logs`, { params: { tail: 50 } })
    serviceLogs.value = res.data?.logs || ''
    logsDialogVisible.value = true
  } catch (err) { showToast('error', errorMessage(err)) } finally { serviceLogLoading.value = '' }
}

async function fetchJoinCommand(role) {
  try {
    const res = await axios.get('/api/ops/swarm/join-command', { params: { role } })
    joinCommand.value = res.data?.command || ''
  } catch (err) { showToast('error', errorMessage(err)) }
}

onMounted(fetchAll)
</script>

<style scoped>
.ops-view { padding: 24px; }
.ops-section { max-width: 1480px; }
.editor-head p, .config-note, .ops-note { color: var(--el-text-color-secondary); font-size: 13px; }
.ops-actions, .editor-actions, .editor-footer-actions, .join-tools { display: flex; gap: 8px; flex-wrap: wrap; }
.ops-note { margin-bottom: 12px; line-height: 1.5; }
.join-tools { margin-bottom: 12px; }
.join-command { margin-bottom: 12px; }
.config-layout { display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 16px; }
.config-list { display: flex; flex-direction: column; gap: 8px; }
.config-list .el-button { justify-content: flex-start; margin-left: 0; }
.editor-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 10px; }
.editor-head h3 { font-size: 16px; font-weight: 650; margin-bottom: 4px; }
.editor-foot { display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-top: 10px; }
.editor-footer-actions { justify-content: flex-end; flex-shrink: 0; }
.config-note { margin: 0; }
.scale-dialog { display: flex; flex-direction: column; gap: 12px; }
.service-actions { display: flex; gap: 8px; flex-wrap: nowrap; }
.service-actions .el-button { margin-left: 0; }
.ops-service-logs { max-height: 620px; }
:deep(textarea) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; font-size: 13px; line-height: 1.5; }
</style>
