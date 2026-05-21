<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

type DetectionStatus = {
  enabled: boolean
  source: string
  model_name: string | null
  frame_id: string
  timestamp: string
  objects: Array<{
    class_name: string
    confidence: number
    bbox_xyxy: number[]
    current_frame?: boolean
    recently_seen?: boolean
    last_seen_at?: string | null
    age_s?: number | null
  }>
  events: Array<{
    event_type: string
    level: string
    message: string
  }>
}

type RobotState = {
  robot_pose: {
    x: number
    y: number
    yaw: number
    frame_id: string
    timestamp: string
  }
  nav_status: {
    mode: string
    state: string
    current_goal: string | null
    remaining_distance: number | null
  }
  task_status: {
    task_id: string
    task_type: string
    state: string
    progress: number
    source: string
  }
  device_status: {
    battery_percent: number | null
    emergency_stop: boolean
    fault_code: string | null
    online: boolean
  }
  env_sensor: {
    temperature_c: number | null
    humidity_percent: number | null
    status: string
  }
  system_mode: {
    mode: string
    updated_at: string
  }
  detection_status: DetectionStatus | null
  updated_at: string
}

type AlertEvent = {
  alert_id: string
  level: string
  message: string
  source: string
  timestamp: string
  acknowledged: boolean
}

type StateResponse = {
  success: boolean
  data: RobotState
}

type AlertsResponse = {
  success: boolean
  data: AlertEvent[]
}

type MissionActionResponse = {
  success: boolean
  data: {
    accepted: boolean
    command: string
    detail: string
  }
}

type VoiceTaskStatus = {
  task_type: string
  state: string
  progress: number
  source: string
}

type VoiceCommandResponse = {
  success: boolean
  data: {
    accepted: boolean
    intent: string | null
    command: string | null
    payload: Record<string, string | number | boolean | null>
    confidence: number
    need_confirm: boolean
    detail: string
    task_status: VoiceTaskStatus | null
  }
}

type VoiceRecordCommandResult = {
  recognized_text: string
  raw_text: string
  asr_backend: string
  asr_time_s: number
  model_load_time_s: number | null
  intent: string | null
  command: string | null
  payload: Record<string, string | number | boolean | null>
  waypoint_id: string | null
  accepted: boolean
  need_confirm: boolean
  detail: string
  error: string | null
  task_status: VoiceTaskStatus | null
  audio_path: string | null
  duration: number
  audio_device: string
  audio_retained: boolean
}

type VoiceRecordCommandResponse = {
  success: boolean
  data: VoiceRecordCommandResult | null
  error: string | null
  detail: string | null
}

type ModeSwitchResponse = {
  success: boolean
  data: {
    accepted: boolean
    detail: string
    system_mode: {
      mode: string
    }
  }
}

type ImuEnvelope = {
  source: string
  updated_at: string
  imu: {
    frame_id: string
    timestamp: string
    orientation: {
      x: number
      y: number
      z: number
      w: number
    }
    euler_deg?: {
      yaw: number
      pitch: number
      roll: number
    } | null
    angular_velocity: {
      x: number
      y: number
      z: number
    }
    linear_acceleration: {
      x: number
      y: number
      z: number
    }
  }
}

type ImuResponse = {
  success: boolean
  data: ImuEnvelope | null
}

const state = ref<RobotState | null>(null)
const alerts = ref<AlertEvent[]>([])
const imu = ref<ImuEnvelope | null>(null)
const waypointId = ref('mock-waypoint')
const textCommand = ref('去一号点')
const voiceResult = ref<VoiceCommandResponse['data'] | null>(null)
const voiceRecordResult = ref<VoiceRecordCommandResult | null>(null)
const voiceRecordError = ref('')
const voiceRecordStatus = ref('空闲')
const voiceRecordDuration = ref(3)
const connectionLabel = ref('连接中')
const imuConnectionLabel = ref('IMU 流连接中')
const actionMessage = ref('等待命令')
const isSending = ref(false)
const isSendingTextCommand = ref(false)
const isRecordingVoice = ref(false)
const isSwitchingMode = ref(false)
const wsConnected = ref(false)
const imuWsConnected = ref(false)
const shouldReconnect = ref(true)
const latestFrameUrl = ref('')
const latestFrameAvailable = ref(false)

let socket: WebSocket | null = null
let imuSocket: WebSocket | null = null
let alertsTimer: number | null = null
let stateTimer: number | null = null
let latestFrameTimer: number | null = null

const onlineStatus = computed(() => {
  if (!state.value) {
    return '未连接'
  }

  if (state.value.system_mode.mode === 'mock') {
    return wsConnected.value ? '在线（Mock）' : '离线（Mock）'
  }

  if (state.value.device_status.fault_code === 'waiting-for-real-state') {
    return '等待 NUC'
  }

  if (state.value.device_status.fault_code === 'nuc-state-timeout') {
    return 'NUC 状态超时'
  }

  if (state.value.device_status.fault_code === 'nuc-bridge-unreachable') {
    return 'NUC Bridge 离线'
  }

  return wsConnected.value && state.value.device_status.online ? '在线（Real）' : '离线（Real）'
})

const currentTaskLabel = computed(() => {
  if (!state.value) {
    return '暂无任务'
  }

  return `${state.value.task_status.task_type} / ${state.value.task_status.state}`
})

const currentGoalLabel = computed(() => state.value?.nav_status.current_goal ?? '未设置')

const systemModeLabel = computed(() => {
  if (!state.value) {
    return '--'
  }

  return state.value.system_mode.mode.toUpperCase()
})

const transportStatusLabel = computed(() => {
  if (!state.value) {
    return '等待状态'
  }

  if (state.value.system_mode.mode === 'mock') {
    return '本地 mock generator'
  }

  if (state.value.device_status.fault_code === 'waiting-for-real-state') {
    return '已切到 real，等待 NUC 首包'
  }

  if (state.value.device_status.fault_code === 'nuc-state-timeout') {
    return 'NUC 状态超时，等待恢复'
  }

  if (state.value.device_status.fault_code === 'nuc-bridge-unreachable') {
    return 'NUC 命令桥异常'
  }

  return 'NUC real bridge 已连接'
})

const batteryLabel = computed(() => {
  if (!state.value) {
    return '--'
  }

  return `${state.value.device_status.battery_percent}%`
})

const estopLabel = computed(() => {
  if (!state.value) {
    return '--'
  }

  return state.value.device_status.emergency_stop ? '已触发' : '正常'
})

const lastUpdatedLabel = computed(() => {
  if (!state.value) {
    return '--'
  }

  return formatTime(state.value.updated_at)
})

const imuUpdatedLabel = computed(() => {
  if (!imu.value) {
    return '--'
  }

  return formatTime(imu.value.updated_at)
})

const detectionStatusLabel = computed(() => {
  const detection = state.value?.detection_status
  if (!detection) {
    return 'offline'
  }

  return detection.enabled ? 'enabled' : 'offline'
})

const currentDetectionObjects = computed(() => {
  return state.value?.detection_status?.objects.filter((object) => object.current_frame !== false) ?? []
})

const recentDetectionObjects = computed(() => {
  return state.value?.detection_status?.objects.filter((object) => object.recently_seen && object.current_frame === false) ?? []
})

const latestDetectionObjectLabel = computed(() => {
  const object = currentDetectionObjects.value[0] ?? recentDetectionObjects.value[0]
  if (!object) {
    return 'no object'
  }

  return formatDetectionObject(object)
})

const currentDetectionLabel = computed(() => {
  if (currentDetectionObjects.value.length === 0) {
    return '当前帧无目标'
  }
  return currentDetectionObjects.value.slice(0, 3).map(formatDetectionObject).join(' / ')
})

const recentDetectionLabel = computed(() => {
  if (recentDetectionObjects.value.length === 0) {
    return '无短时保持目标'
  }
  return recentDetectionObjects.value.slice(0, 3).map(formatDetectionObject).join(' / ')
})

const latestDetectionEventLabel = computed(() => {
  const event = state.value?.detection_status?.events[0]
  return event ? `${event.event_type} · ${event.message}` : 'no event'
})

const detectionEventItems = computed(() => state.value?.detection_status?.events ?? [])

const latestVoiceSummary = computed(() => {
  if (voiceRecordResult.value) {
    return `${voiceRecordResult.value.recognized_text || '--'} / ${voiceRecordResult.value.intent ?? '--'} / ${voiceRecordResult.value.accepted ? '已受理' : '未受理'}`
  }
  if (voiceResult.value) {
    return `${textCommand.value || '--'} / ${voiceResult.value.intent ?? '--'} / ${voiceResult.value.accepted ? '已受理' : '未受理'}`
  }
  return '暂无语音或文本结果'
})

const voiceRecordStatusHint = computed(() => {
  if (isRecordingVoice.value) {
    return '正在录音并识别，请说话...'
  }

  if (voiceRecordError.value) {
    return '失败'
  }

  if (voiceRecordResult.value) {
    return voiceRecordResult.value.accepted ? '已受理' : '未受理'
  }

  return '空闲'
})

const voiceRecordAcceptedLabel = computed(() => {
  if (!voiceRecordResult.value) {
    return '--'
  }

  return voiceRecordResult.value.accepted ? '已受理' : '未受理'
})

const voiceRecordNoCommandLabel = computed(() => {
  if (!voiceRecordResult.value) {
    return ''
  }

  if (!voiceRecordResult.value.accepted || voiceRecordResult.value.intent === 'unknown') {
    return '未识别到可执行任务命令'
  }

  return ''
})

onMounted(async () => {
  await Promise.all([loadState(), loadAlerts(), loadImu()])
  connectWebSocket()
  connectImuWebSocket()
  alertsTimer = window.setInterval(() => {
    void loadAlerts()
  }, 5000)
  refreshLatestFrame()
  latestFrameTimer = window.setInterval(refreshLatestFrame, 2000)
  stateTimer = window.setInterval(() => {
    void Promise.all([loadState(), loadImu()])
  }, 4000)
})

onBeforeUnmount(() => {
  shouldReconnect.value = false

  if (socket) {
    socket.close()
  }

  if (imuSocket) {
    imuSocket.close()
  }

  if (alertsTimer !== null) {
    window.clearInterval(alertsTimer)
  }

  if (stateTimer !== null) {
    window.clearInterval(stateTimer)
  }

  if (latestFrameTimer !== null) {
    window.clearInterval(latestFrameTimer)
  }
})

async function loadState() {
  try {
    const response = await fetch('/api/state/latest')
    if (!response.ok) {
      throw new Error('状态接口不可用')
    }

    const payload = (await response.json()) as StateResponse
    state.value = payload.data
  } catch (error) {
    actionMessage.value = error instanceof Error ? error.message : '状态加载失败'
  }
}

async function loadAlerts() {
  try {
    const response = await fetch('/api/alerts')
    if (!response.ok) {
      throw new Error('告警接口不可用')
    }

    const payload = (await response.json()) as AlertsResponse
    alerts.value = payload.data
  } catch {
    alerts.value = []
  }
}

async function loadImu() {
  try {
    const response = await fetch('/api/imu/latest')
    if (!response.ok) {
      throw new Error('IMU 接口不可用')
    }

    const payload = (await response.json()) as ImuResponse
    imu.value = payload.data
  } catch {
    imu.value = null
  }
}

function refreshLatestFrame() {
  latestFrameAvailable.value = true
  latestFrameUrl.value = `/api/perception/latest_frame?t=${Date.now()}`
}

function handleLatestFrameError() {
  latestFrameAvailable.value = false
}

function handleLatestFrameLoad() {
  latestFrameAvailable.value = true
}

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${protocol}://${window.location.host}/ws/state`)

  socket.onopen = () => {
    wsConnected.value = true
    connectionLabel.value = '实时流已连接'
    void loadState()
  }

  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data) as { type: string; data: RobotState }
    if (payload.type === 'robot_state') {
      state.value = payload.data
    }
  }

  socket.onclose = () => {
    wsConnected.value = false
    connectionLabel.value = '实时流断开，3 秒后重连'
    if (shouldReconnect.value) {
      window.setTimeout(connectWebSocket, 3000)
    }
  }

  socket.onerror = () => {
    connectionLabel.value = '实时流异常'
  }
}

function connectImuWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  imuSocket = new WebSocket(`${protocol}://${window.location.host}/ws/imu`)

  imuSocket.onopen = () => {
    imuWsConnected.value = true
    imuConnectionLabel.value = 'IMU 流已连接'
    void loadImu()
  }

  imuSocket.onmessage = (event) => {
    const payload = JSON.parse(event.data) as { type: string; data: ImuEnvelope | null }
    if (payload.type === 'imu') {
      imu.value = payload.data
    }
  }

  imuSocket.onclose = () => {
    imuWsConnected.value = false
    imuConnectionLabel.value = 'IMU 流断开，3 秒后重连'
    if (shouldReconnect.value) {
      window.setTimeout(connectImuWebSocket, 3000)
    }
  }

  imuSocket.onerror = () => {
    imuConnectionLabel.value = 'IMU 流异常'
  }
}

async function sendMission(
  path: string,
  body: Record<string, string | null>,
  successText: string,
) {
  isSending.value = true

  try {
    const response = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      throw new Error('任务接口调用失败')
    }

    const payload = (await response.json()) as MissionActionResponse
    actionMessage.value = payload.data.detail || successText
    await Promise.all([loadState(), loadAlerts()])
  } catch (error) {
    actionMessage.value = error instanceof Error ? error.message : '命令发送失败'
  } finally {
    isSending.value = false
  }
}

async function sendTextCommand() {
  if (!textCommand.value.trim()) {
    voiceResult.value = null
    actionMessage.value = '请输入文本命令'
    return
  }

  isSendingTextCommand.value = true

  try {
    const response = await fetch('/api/voice/text_command', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        text: textCommand.value,
        source: 'dashboard-text',
        requested_by: 'dashboard',
      }),
    })
    if (!response.ok) {
      throw new Error('文本命令接口调用失败')
    }

    const payload = (await response.json()) as VoiceCommandResponse
    voiceResult.value = payload.data
    actionMessage.value = payload.data.detail
    await Promise.all([loadState(), loadAlerts()])
  } catch (error) {
    actionMessage.value = error instanceof Error ? error.message : '文本命令发送失败'
  } finally {
    isSendingTextCommand.value = false
  }
}

async function recordVoiceCommand() {
  if (isRecordingVoice.value) {
    return
  }

  isRecordingVoice.value = true
  voiceRecordStatus.value = '录音识别中'
  voiceRecordError.value = ''
  voiceRecordResult.value = null

  try {
    const response = await fetch('/api/voice/record_command', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        duration: voiceRecordDuration.value,
        source: 'dashboard-record-button',
        requested_by: 'operator',
        keep_audio: true,
      }),
    })

    let payload: VoiceRecordCommandResponse | null = null
    try {
      payload = (await response.json()) as VoiceRecordCommandResponse
    } catch {
      payload = null
    }

    if (!response.ok) {
      throw new Error(payload?.detail || payload?.error || '板端录音接口调用失败')
    }

    if (!payload?.success) {
      voiceRecordResult.value = payload?.data ?? null
      const message = payload?.detail || payload?.error || payload?.data?.error || '板端录音识别失败'
      voiceRecordError.value = message
      voiceRecordStatus.value = '失败'
      actionMessage.value = message
      return
    }

    if (!payload.data) {
      throw new Error('板端录音接口未返回识别结果')
    }

    voiceRecordResult.value = payload.data
    voiceRecordStatus.value = payload.data.accepted && payload.data.intent !== 'unknown' ? '成功' : '未受理'
    actionMessage.value = payload.data.accepted ? payload.data.detail : '未识别到可执行任务命令'
    await Promise.all([loadState(), loadAlerts()])
  } catch (error) {
    const message = error instanceof Error ? error.message : '板端录音识别失败'
    voiceRecordError.value = message
    voiceRecordStatus.value = '失败'
    actionMessage.value = message
  } finally {
    isRecordingVoice.value = false
  }
}

async function switchMode(mode: 'mock' | 'real') {
  isSwitchingMode.value = true

  try {
    const response = await fetch('/api/system/mode/switch', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        mode,
        source: 'web',
        requested_by: 'dashboard',
      }),
    })
    if (!response.ok) {
      throw new Error('模式切换失败')
    }

    const payload = (await response.json()) as ModeSwitchResponse
    actionMessage.value = payload.data.detail
    await Promise.all([loadState(), loadAlerts()])
  } catch (error) {
    actionMessage.value = error instanceof Error ? error.message : '模式切换失败'
  } finally {
    isSwitchingMode.value = false
  }
}

function formatNumber(value: number | null | undefined, suffix = '', decimals = 3) {
  if (value === null || value === undefined) {
    return '--'
  }

  return `${value.toFixed(decimals)}${suffix}`
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString('zh-CN', { hour12: false })
}

function formatDetectionObject(object: { class_name: string; confidence: number; age_s?: number | null }) {
  const age = object.age_s && object.age_s > 0 ? ` / ${object.age_s.toFixed(1)}s 前` : ''
  return `${object.class_name} ${object.confidence.toFixed(2)}${age}`
}
</script>

<template>
  <main class="dashboard">
    <section class="panel hero-panel">
      <div>
        <p class="eyebrow">Phase 2 Dashboard</p>
        <h1>RK3588 状态中台</h1>
        <p class="description">
          面向 Phase 1 / Phase 2 联调用的最小看板，支持 mock 中台与 NUC real bridge 的状态展示和任务入口。
        </p>
      </div>
      <div class="stream-status">
        <span class="status-dot" :class="{ live: wsConnected }"></span>
        <strong>{{ connectionLabel }}</strong>
        <small>最近更新时间 {{ lastUpdatedLabel }}</small>
        <small>{{ transportStatusLabel }}</small>
        <div class="button-row compact-row">
          <button
            :disabled="isSwitchingMode || state?.system_mode.mode === 'mock'"
            class="secondary"
            @click="switchMode('mock')"
          >
            切到 Mock
          </button>
          <button
            :disabled="isSwitchingMode || state?.system_mode.mode === 'real'"
            @click="switchMode('real')"
          >
            切到 Real
          </button>
        </div>
      </div>
    </section>

    <section class="status-grid">
      <article class="card">
        <span class="card-label">系统模式</span>
        <strong>{{ systemModeLabel }}</strong>
      </article>
      <article class="card">
        <span class="card-label">在线状态</span>
        <strong>{{ onlineStatus }}</strong>
      </article>
      <article class="card">
        <span class="card-label">数据链路</span>
        <strong>{{ transportStatusLabel }}</strong>
      </article>
      <article class="card">
        <span class="card-label">当前任务</span>
        <strong>{{ currentTaskLabel }}</strong>
      </article>
      <article class="card">
        <span class="card-label">当前目标</span>
        <strong>{{ currentGoalLabel }}</strong>
      </article>
      <article class="card">
        <span class="card-label">电量</span>
        <strong>{{ batteryLabel }}</strong>
      </article>
      <article class="card">
        <span class="card-label">急停状态</span>
        <strong>{{ estopLabel }}</strong>
      </article>
      <article class="card">
        <span class="card-label">任务进度</span>
        <strong>{{ formatNumber(state?.task_status.progress, '%') }}</strong>
      </article>
    </section>

    <section class="content-grid">
      <article class="panel section-panel">
        <div class="section-header">
          <div>
            <p class="section-kicker">Mission</p>
            <h2>任务操作</h2>
          </div>
          <span class="hint-text">{{ actionMessage }}</span>
        </div>

        <label class="field">
          <span>目标点 ID</span>
          <input v-model="waypointId" type="text" placeholder="例如 mock-waypoint" />
        </label>

        <div class="button-row">
          <button
            :disabled="isSending || !waypointId"
            @click="sendMission('/api/mission/go_to_waypoint', { waypoint_id: waypointId, source: 'web', requested_by: 'dashboard' }, '已发送前往目标点命令')"
          >
            前往目标点
          </button>
          <button
            :disabled="isSending"
            class="secondary"
            @click="sendMission('/api/mission/pause', { source: 'web', requested_by: 'dashboard' }, '已发送暂停命令')"
          >
            暂停
          </button>
          <button
            :disabled="isSending"
            class="secondary"
            @click="sendMission('/api/mission/resume', { source: 'web', requested_by: 'dashboard' }, '已发送恢复命令')"
          >
            恢复
          </button>
          <button
            :disabled="isSending"
            class="warn"
            @click="sendMission('/api/mission/return_home', { source: 'web', requested_by: 'dashboard' }, '已发送返航命令')"
          >
            返回 Home
          </button>
        </div>
      </article>

      <article class="panel section-panel">
        <div class="section-header">
          <div>
            <p class="section-kicker">Voice</p>
            <h2>语音/文本任务入口</h2>
          </div>
          <span class="hint-text">{{ latestVoiceSummary }}</span>
        </div>

        <label class="field">
          <span>文本命令</span>
          <input v-model="textCommand" type="text" placeholder="例如 去一号点" @keyup.enter="sendTextCommand" />
        </label>

        <div class="button-row">
          <button :disabled="isSendingTextCommand || !textCommand.trim()" @click="sendTextCommand">
            发送
          </button>
        </div>

        <div v-if="voiceResult" class="detail-grid command-result-grid">
          <div class="detail-item">
            <span>Intent</span>
            <strong>{{ voiceResult.intent ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>Command</span>
            <strong>{{ voiceResult.command ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>Waypoint</span>
            <strong>{{ voiceResult.payload.waypoint_id ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>Accepted</span>
            <strong>{{ String(voiceResult.accepted) }}</strong>
          </div>
          <div class="detail-item wide-detail">
            <span>Detail</span>
            <strong>{{ voiceResult.detail }}</strong>
          </div>
        </div>
        <div v-else class="empty-state">等待文本命令</div>
      </article>

      <article class="panel section-panel voice-record-panel">
        <div class="section-header">
          <div>
            <p class="section-kicker">Server Voice</p>
            <h2>语音任务入口</h2>
          </div>
          <span class="hint-text">{{ voiceRecordStatusHint }}</span>
        </div>

        <div class="voice-record-toolbar">
          <label class="field compact-field">
            <span>录音时长</span>
            <select v-model.number="voiceRecordDuration" :disabled="isRecordingVoice">
              <option :value="2">2 秒</option>
              <option :value="3">3 秒</option>
              <option :value="5">5 秒</option>
            </select>
          </label>

          <button :disabled="isRecordingVoice" @click="recordVoiceCommand">
            {{ isRecordingVoice ? '录音识别中...' : '开始板端录音识别' }}
          </button>
        </div>

        <p v-if="isRecordingVoice" class="inline-status">正在录音并识别，请说话...</p>
        <p v-if="voiceRecordNoCommandLabel" class="inline-status warn-status">
          {{ voiceRecordNoCommandLabel }}
        </p>
        <p v-if="voiceRecordError" class="inline-status error-status">错误信息：{{ voiceRecordError }}</p>

        <div v-if="voiceRecordResult" class="detail-grid command-result-grid">
          <div class="detail-item">
            <span>状态</span>
            <strong>{{ voiceRecordStatus }}</strong>
          </div>
          <div class="detail-item">
            <span>识别文本</span>
            <strong>{{ voiceRecordResult.recognized_text || '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>解析意图</span>
            <strong>{{ voiceRecordResult.intent ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>命令</span>
            <strong>{{ voiceRecordResult.command ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>目标点</span>
            <strong>{{ voiceRecordResult.waypoint_id ?? voiceRecordResult.payload.waypoint_id ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>是否受理</span>
            <strong>{{ voiceRecordAcceptedLabel }}</strong>
          </div>
          <div class="detail-item">
            <span>ASR 后端</span>
            <strong>{{ voiceRecordResult.asr_backend }}</strong>
          </div>
          <div class="detail-item">
            <span>ASR 耗时</span>
            <strong>{{ formatNumber(voiceRecordResult.asr_time_s, ' s') }}</strong>
          </div>
          <div class="detail-item">
            <span>模型加载</span>
            <strong>{{ formatNumber(voiceRecordResult.model_load_time_s, ' s') }}</strong>
          </div>
          <div class="detail-item">
            <span>任务状态</span>
            <strong>{{ voiceRecordResult.task_status?.state ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>任务类型</span>
            <strong>{{ voiceRecordResult.task_status?.task_type ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>任务进度</span>
            <strong>{{ formatNumber(voiceRecordResult.task_status?.progress, '%') }}</strong>
          </div>
          <div class="detail-item">
            <span>任务来源</span>
            <strong>{{ voiceRecordResult.task_status?.source ?? '--' }}</strong>
          </div>
          <div class="detail-item wide-detail">
            <span>提示信息</span>
            <strong>{{ voiceRecordResult.detail || voiceRecordResult.error || '--' }}</strong>
          </div>
          <div class="detail-item wide-detail">
            <span>音频文件</span>
            <strong>{{ voiceRecordResult.audio_path ?? '--' }}</strong>
          </div>
        </div>
        <div v-else class="empty-state">等待板端录音识别</div>
      </article>

      <article class="panel section-panel">
        <div class="section-header">
          <div>
            <p class="section-kicker">Sensors</p>
            <h2>环境传感器</h2>
          </div>
        </div>

        <div class="detail-grid">
          <div class="detail-item">
            <span>温度</span>
            <strong>{{ formatNumber(state?.env_sensor.temperature_c, ' °C') }}</strong>
          </div>
          <div class="detail-item">
            <span>湿度</span>
            <strong>{{ formatNumber(state?.env_sensor.humidity_percent, ' %') }}</strong>
          </div>
          <div class="detail-item">
            <span>传感器状态</span>
            <strong>{{ state?.env_sensor.status ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>故障码</span>
            <strong>{{ state?.device_status.fault_code ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>导航状态</span>
            <strong>{{ state?.nav_status.state ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>剩余距离</span>
            <strong>{{ formatNumber(state?.nav_status.remaining_distance, ' m') }}</strong>
          </div>
          <div class="detail-item">
            <span>位姿</span>
            <strong>
              {{ formatNumber(state?.robot_pose.x) }},
              {{ formatNumber(state?.robot_pose.y) }},
              {{ formatNumber(state?.robot_pose.yaw) }}
            </strong>
          </div>
        </div>
      </article>

      <article class="panel section-panel">
        <div class="section-header">
          <div>
            <p class="section-kicker">IMU</p>
            <h2>IMU 调试面板</h2>
          </div>
          <span class="hint-text">{{ imuConnectionLabel }} · 更新时间 {{ imuUpdatedLabel }}</span>
        </div>

        <div v-if="imu" class="detail-grid">
          <div class="detail-item">
            <span>Frame ID</span>
            <strong>{{ imu.imu.frame_id }}</strong>
          </div>
          <div class="detail-item">
            <span>样本时间</span>
            <strong>{{ formatTime(imu.imu.timestamp) }}</strong>
          </div>
          <div class="detail-item">
            <span>欧拉角 (deg)</span>
            <strong v-if="imu.imu.euler_deg" class="value-block">
              yaw={{ formatNumber(imu.imu.euler_deg.yaw) }}
              pitch={{ formatNumber(imu.imu.euler_deg.pitch) }}
              roll={{ formatNumber(imu.imu.euler_deg.roll) }}
            </strong>
            <strong v-else>--</strong>
          </div>
          <div class="detail-item">
            <span>四元数</span>
            <strong class="value-block">
              x={{ formatNumber(imu.imu.orientation.x) }}
              y={{ formatNumber(imu.imu.orientation.y) }}
              z={{ formatNumber(imu.imu.orientation.z) }}
              w={{ formatNumber(imu.imu.orientation.w) }}
            </strong>
          </div>
          <div class="detail-item">
            <span>角速度</span>
            <strong class="value-block">
              x={{ formatNumber(imu.imu.angular_velocity.x) }}
              y={{ formatNumber(imu.imu.angular_velocity.y) }}
              z={{ formatNumber(imu.imu.angular_velocity.z) }}
            </strong>
          </div>
          <div class="detail-item">
            <span>线加速度</span>
            <strong class="value-block">
              x={{ formatNumber(imu.imu.linear_acceleration.x) }}
              y={{ formatNumber(imu.imu.linear_acceleration.y) }}
              z={{ formatNumber(imu.imu.linear_acceleration.z) }}
            </strong>
          </div>
          <div class="detail-item">
            <span>数据来源</span>
            <strong>{{ imu.source }}</strong>
          </div>
        </div>
        <div v-else class="empty-state">当前暂无 IMU 样本</div>
      </article>

      <article class="panel section-panel">
        <div class="section-header">
          <div>
            <p class="section-kicker">Perception</p>
            <h2>视觉检测状态</h2>
          </div>
          <span class="hint-text">{{ detectionStatusLabel }}</span>
        </div>

        <div class="latest-frame-box">
          <img
            v-if="latestFrameAvailable && latestFrameUrl"
            :src="latestFrameUrl"
            alt="最新识别画面"
            @error="handleLatestFrameError"
            @load="handleLatestFrameLoad"
          />
          <div v-else class="latest-frame-placeholder">暂无识别画面</div>
        </div>

        <div class="detail-grid">
          <div class="detail-item">
            <span>来源</span>
            <strong>{{ state?.detection_status?.source ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>模型</span>
            <strong>{{ state?.detection_status?.model_name ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>最近目标</span>
            <strong>{{ latestDetectionObjectLabel }}</strong>
          </div>
          <div class="detail-item">
            <span>当前检测</span>
            <strong>{{ currentDetectionLabel }}</strong>
          </div>
          <div class="detail-item">
            <span>最近检测</span>
            <strong>{{ recentDetectionLabel }}</strong>
          </div>
          <div class="detail-item">
            <span>最近事件</span>
            <strong>{{ latestDetectionEventLabel }}</strong>
          </div>
          <div class="detail-item">
            <span>更新时间</span>
            <strong>{{ state?.detection_status ? formatTime(state.detection_status.timestamp) : '--' }}</strong>
          </div>
          <div class="detail-item wide-detail">
            <span>视觉事件</span>
            <strong v-if="detectionEventItems.length === 0">暂无事件</strong>
            <strong v-else class="value-block">
              <span v-for="event in detectionEventItems" :key="`${event.event_type}-${event.message}`">
                {{ event.level }} / {{ event.event_type }} / {{ event.message }}
              </span>
            </strong>
          </div>
        </div>
      </article>

      <article class="panel section-panel alerts-panel">
        <div class="section-header">
          <div>
            <p class="section-kicker">Alerts</p>
            <h2>最近告警</h2>
          </div>
        </div>

        <ul class="alert-list">
          <li v-for="alert in alerts" :key="alert.alert_id" class="alert-item">
            <div>
              <strong>{{ alert.message }}</strong>
              <p>{{ alert.source }} · {{ formatTime(alert.timestamp) }}</p>
            </div>
            <span class="alert-level">{{ alert.level }}</span>
          </li>
          <li v-if="alerts.length === 0" class="empty-state">暂无告警</li>
        </ul>
      </article>
    </section>
  </main>
</template>
