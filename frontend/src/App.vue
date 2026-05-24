<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import NavMapPlaceholder from './components/NavMapPlaceholder.vue'
import VoiceConfirmDialog from './components/VoiceConfirmDialog.vue'

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

type VoicePayloadValue = string | number | boolean | null

type VoiceCommandResult = {
  accepted: boolean
  intent: string | null
  command: string | null
  payload: Record<string, VoicePayloadValue>
  confidence: number
  need_confirm?: boolean
  pending_command_id?: string | null
  recognized_text?: string
  waypoint_id?: string | null
  parser?: string
  llm_backend?: string | null
  llm_model?: string | null
  detail: string
  error?: string | null
  task_status: VoiceTaskStatus | null
}

type VoiceCommandResponse = {
  success: boolean
  data: VoiceCommandResult
}

type VoiceRecordCommandResult = VoiceCommandResult & {
  recognized_text: string
  raw_text: string | null
  asr_backend: string
  asr_time_s: number | null
  model_load_time_s: number | null
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

type StatusTone = 'success' | 'info' | 'warning' | 'danger' | 'muted'

type DashboardEventItem = {
  id: string
  time: string
  source: string
  level: string
  message: string
  tone: StatusTone
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
const pendingVoiceCommand = ref<VoiceCommandResult | null>(null)
const pendingVoiceSource = ref<'text' | 'record' | null>(null)
const voiceConfirmError = ref('')
const connectionLabel = ref('连接中')
const imuConnectionLabel = ref('IMU 流连接中')
const actionMessage = ref('等待命令')
const isSending = ref(false)
const isSendingTextCommand = ref(false)
const isRecordingVoice = ref(false)
const isConfirmingVoiceCommand = ref(false)
const isSwitchingMode = ref(false)
const wsConnected = ref(false)
const imuWsConnected = ref(false)
const shouldReconnect = ref(true)
const latestFrameUrl = ref('')
const latestFrameAvailable = ref(false)
const currentClockLabel = ref('--')

let socket: WebSocket | null = null
let imuSocket: WebSocket | null = null
let alertsTimer: number | null = null
let stateTimer: number | null = null
let latestFrameTimer: number | null = null
let clockTimer: number | null = null

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
  const battery = state.value?.device_status.battery_percent
  if (battery === null || battery === undefined) {
    return '--'
  }

  return `${battery}%`
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

const latestAlert = computed(() => alerts.value[0] ?? null)

const onlineTone = computed<StatusTone>(() => {
  if (!state.value) {
    return 'muted'
  }
  if (state.value.device_status.fault_code || state.value.device_status.emergency_stop) {
    return 'danger'
  }
  if (onlineStatus.value.includes('等待') || onlineStatus.value.includes('超时')) {
    return 'warning'
  }
  return onlineStatus.value.includes('在线') ? 'success' : 'muted'
})

const taskTone = computed<StatusTone>(() => {
  const taskState = state.value?.task_status.state?.toLowerCase() ?? ''
  if (!taskState || taskState === 'idle') {
    return 'muted'
  }
  if (taskState.includes('running') || taskState.includes('active') || taskState.includes('navigating')) {
    return 'info'
  }
  if (taskState.includes('pause')) {
    return 'warning'
  }
  if (taskState.includes('fail') || taskState.includes('error')) {
    return 'danger'
  }
  return 'info'
})

const batteryTone = computed<StatusTone>(() => {
  if (!state.value) {
    return 'muted'
  }
  if (state.value.device_status.emergency_stop || state.value.device_status.fault_code) {
    return 'danger'
  }
  const battery = state.value.device_status.battery_percent
  if (battery === null) {
    return 'muted'
  }
  if (battery < 20) {
    return 'danger'
  }
  if (battery < 40) {
    return 'warning'
  }
  return 'success'
})

const detectionTone = computed<StatusTone>(() => {
  const detection = state.value?.detection_status
  if (!detection) {
    return 'muted'
  }
  return detection.enabled ? 'success' : 'muted'
})

const latestAlertTone = computed<StatusTone>(() => alertTone(latestAlert.value?.level))

const navGoal = computed(() => ({
  id: state.value?.nav_status.current_goal ?? state.value?.task_status.task_id ?? undefined,
}))

const dashboardEvents = computed<DashboardEventItem[]>(() => {
  const items: DashboardEventItem[] = []

  if (voiceRecordResult.value) {
    items.push({
      id: 'voice-record-latest',
      time: '刚刚',
      source: 'Voice',
      level: voiceRecordResult.value.need_confirm ? 'pending' : voiceRecordResult.value.accepted ? 'info' : 'warning',
      message: `${voiceRecordResult.value.recognized_text || '--'} / ${voiceRecordResult.value.intent ?? '--'} / ${voiceRecordResult.value.detail || voiceRecordResult.value.error || '--'}`,
      tone: voiceRecordResult.value.need_confirm ? 'warning' : voiceRecordResult.value.accepted ? 'info' : 'warning',
    })
  }

  if (voiceResult.value) {
    items.push({
      id: 'voice-text-latest',
      time: '刚刚',
      source: 'Text/LLM',
      level: voiceResult.value.need_confirm ? 'pending' : voiceResult.value.accepted ? 'info' : 'warning',
      message: `${voiceResult.value.recognized_text || textCommand.value || '--'} / ${voiceResult.value.intent ?? '--'} / ${voiceResult.value.detail || voiceResult.value.error || '--'}`,
      tone: voiceResult.value.need_confirm ? 'warning' : voiceResult.value.accepted ? 'info' : 'warning',
    })
  }

  if (state.value) {
    items.push({
      id: 'mission-current',
      time: formatTime(state.value.updated_at),
      source: 'Mission',
      level: state.value.task_status.state,
      message: `${state.value.task_status.task_type} / ${state.value.task_status.state} / ${state.value.task_status.progress}%`,
      tone: taskTone.value,
    })
  }

  detectionEventItems.value.slice(0, 4).forEach((event, index) => {
    items.push({
      id: `detection-${index}-${event.event_type}`,
      time: state.value?.detection_status ? formatTime(state.value.detection_status.timestamp) : '--',
      source: 'YOLO',
      level: event.level,
      message: `${event.event_type} / ${event.message}`,
      tone: alertTone(event.level),
    })
  })

  alerts.value.slice(0, 5).forEach((alert) => {
    items.push({
      id: alert.alert_id,
      time: formatTime(alert.timestamp),
      source: alert.source,
      level: alert.level,
      message: alert.message,
      tone: alertTone(alert.level),
    })
  })

  return items.slice(0, 10)
})

const latestVoiceSummary = computed(() => {
  if (voiceRecordResult.value) {
    return `${voiceRecordResult.value.recognized_text || '--'} / ${voiceRecordResult.value.intent ?? '--'} / ${voiceStatusLabel(voiceRecordResult.value)}`
  }
  if (voiceResult.value) {
    return `${voiceResult.value.recognized_text || textCommand.value || '--'} / ${voiceResult.value.intent ?? '--'} / ${voiceStatusLabel(voiceResult.value)}`
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
    return voiceStatusLabel(voiceRecordResult.value)
  }

  return '空闲'
})

const voiceRecordAcceptedLabel = computed(() => {
  if (!voiceRecordResult.value) {
    return '--'
  }

  return voiceStatusLabel(voiceRecordResult.value)
})

const voiceRecordNoCommandLabel = computed(() => {
  if (!voiceRecordResult.value) {
    return ''
  }

  if (shouldOpenVoiceConfirm(voiceRecordResult.value)) {
    return '移动任务等待确认'
  }

  if (!voiceRecordResult.value.accepted || voiceRecordResult.value.intent === 'unknown') {
    return '未识别到可执行任务命令'
  }

  return ''
})

function voiceStatusLabel(result: VoiceCommandResult) {
  if (shouldOpenVoiceConfirm(result)) {
    return '待确认'
  }
  if (result.accepted) {
    return '已受理'
  }
  return '未受理'
}

function resultWaypointId(result: VoiceCommandResult) {
  return result.waypoint_id ?? valueAsString(result.payload?.waypoint_id)
}

function valueAsString(value: VoicePayloadValue | undefined) {
  if (value === null || value === undefined) {
    return null
  }
  return String(value)
}

function normalizeVoiceResult(result: VoiceCommandResult, recognizedTextFallback = ''): VoiceCommandResult {
  return {
    ...result,
    payload: result.payload ?? {},
    need_confirm: Boolean(result.need_confirm),
    pending_command_id: result.pending_command_id ?? null,
    recognized_text: result.recognized_text || recognizedTextFallback,
    waypoint_id: resultWaypointId(result),
  }
}

function shouldOpenVoiceConfirm(result: VoiceCommandResult | null) {
  return Boolean(result?.need_confirm && result.pending_command_id)
}

function handleVoiceCommandResult(
  result: VoiceCommandResult,
  source: 'text' | 'record',
  recognizedTextFallback = '',
) {
  const normalized = normalizeVoiceResult(result, recognizedTextFallback)

  if (source === 'record') {
    voiceRecordResult.value = normalized as VoiceRecordCommandResult
    voiceRecordStatus.value = voiceStatusLabel(normalized)
  } else {
    voiceResult.value = normalized
  }

  if (shouldOpenVoiceConfirm(normalized)) {
    pendingVoiceCommand.value = normalized
    pendingVoiceSource.value = source
    voiceConfirmError.value = ''
    actionMessage.value = '移动任务需要确认，尚未执行'
    return
  }

  pendingVoiceCommand.value = null
  pendingVoiceSource.value = null
  actionMessage.value = normalized.accepted
    ? normalized.detail
    : normalized.detail || normalized.error || '未识别到可执行任务命令'
}

async function confirmVoiceCommand(
  pendingCommandId: string,
  confirmed: boolean,
  requestedBy = 'operator',
) {
  const response = await fetch('/api/voice/confirm_command', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      pending_command_id: pendingCommandId,
      confirmed,
      requested_by: requestedBy,
    }),
  })

  let payload: VoiceCommandResponse | null = null
  try {
    payload = (await response.json()) as VoiceCommandResponse
  } catch {
    payload = null
  }

  if (!response.ok || !payload?.data) {
    throw new Error(payload?.data?.detail || '确认请求失败，请检查连接')
  }

  return normalizeVoiceResult(payload.data, pendingVoiceCommand.value?.recognized_text ?? '')
}

function closeVoiceConfirmDialog() {
  pendingVoiceCommand.value = null
  pendingVoiceSource.value = null
  voiceConfirmError.value = ''
}

async function handleVoiceConfirm(confirmed: boolean) {
  if (isConfirmingVoiceCommand.value) {
    return
  }

  const pendingId = pendingVoiceCommand.value?.pending_command_id
  if (!pendingId) {
    voiceConfirmError.value = '缺少待确认命令 ID，请重新下达命令'
    return
  }

  isConfirmingVoiceCommand.value = true
  voiceConfirmError.value = ''

  try {
    const result = await confirmVoiceCommand(pendingId, confirmed, 'dashboard')
    const source = pendingVoiceSource.value

    if (source === 'record' && voiceRecordResult.value) {
      voiceRecordResult.value = {
        ...voiceRecordResult.value,
        accepted: result.accepted,
        need_confirm: result.need_confirm,
        pending_command_id: result.pending_command_id,
        intent: result.intent,
        command: result.command,
        payload: result.payload,
        confidence: result.confidence,
        waypoint_id: resultWaypointId(result),
        parser: result.parser,
        llm_backend: result.llm_backend,
        llm_model: result.llm_model,
        detail: result.detail,
        error: result.error,
        task_status: result.task_status,
      }
      voiceRecordStatus.value = confirmed && result.accepted ? '已确认执行' : '已取消'
    } else {
      voiceResult.value = result
    }

    if (confirmed && !result.accepted) {
      const message = result.detail || '确认已过期，请重新下达命令'
      actionMessage.value = message.includes('过期') || message.includes('不存在')
        ? '确认已过期，请重新下达命令'
        : message
      closeVoiceConfirmDialog()
      return
    }

    actionMessage.value = confirmed
      ? result.detail || '任务已确认执行'
      : result.detail || '任务已取消'
    closeVoiceConfirmDialog()
    await Promise.all([loadState(), loadAlerts()])
  } catch (error) {
    const message = error instanceof Error ? error.message : '确认请求失败，请检查连接'
    voiceConfirmError.value = message
    actionMessage.value = message
  } finally {
    isConfirmingVoiceCommand.value = false
  }
}

onMounted(async () => {
  updateClock()
  clockTimer = window.setInterval(updateClock, 1000)
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

  if (clockTimer !== null) {
    window.clearInterval(clockTimer)
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
    handleVoiceCommandResult(payload.data, 'text', textCommand.value)
    if (!shouldOpenVoiceConfirm(payload.data)) {
      await Promise.all([loadState(), loadAlerts()])
    }
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

    handleVoiceCommandResult(payload.data, 'record')
    if (!shouldOpenVoiceConfirm(payload.data)) {
      await Promise.all([loadState(), loadAlerts()])
    }
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

function updateClock() {
  currentClockLabel.value = new Date().toLocaleString('zh-CN', { hour12: false })
}

function toneClass(tone: StatusTone) {
  return `tone-${tone}`
}

function alertTone(level: string | null | undefined): StatusTone {
  const normalized = (level ?? '').toLowerCase()
  if (['error', 'critical', 'fault', 'danger'].some((item) => normalized.includes(item))) {
    return 'danger'
  }
  if (['warn', 'alert', 'pending'].some((item) => normalized.includes(item))) {
    return 'warning'
  }
  if (['info', 'normal', 'ok'].some((item) => normalized.includes(item))) {
    return 'info'
  }
  return normalized ? 'warning' : 'muted'
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
    <header class="command-header">
      <div class="brand-block">
        <p class="eyebrow">QHXD Robot Console</p>
        <h1>配送巡检一体化哨兵机器人中台</h1>
        <p class="header-subtitle">RK3588 车载交互与状态中枢</p>
      </div>

      <div class="header-control-plane">
        <div class="top-status-items" aria-label="系统状态">
          <span class="status-badge mode-badge" :class="toneClass(state?.system_mode.mode === 'real' ? 'info' : 'muted')">
            {{ systemModeLabel }} 模式
          </span>
          <span class="status-badge" :class="toneClass(onlineTone)">NUC {{ onlineStatus }}</span>
          <span class="status-badge" :class="toneClass(wsConnected ? 'success' : 'warning')">
            RK3588 {{ wsConnected ? 'Online' : 'Reconnecting' }}
          </span>
          <span class="status-badge" :class="toneClass(latestAlertTone)">
            告警 {{ latestAlert?.level ?? 'normal' }}
          </span>
          <span class="time-chip">{{ currentClockLabel }}</span>
        </div>

        <div class="mode-switch-group" aria-label="系统模式切换">
          <button
            :disabled="isSwitchingMode || state?.system_mode.mode === 'mock'"
            class="secondary compact-button"
            type="button"
            @click="switchMode('mock')"
          >
            切到 Mock
          </button>
          <button
            :disabled="isSwitchingMode || state?.system_mode.mode === 'real'"
            class="compact-button"
            type="button"
            @click="switchMode('real')"
          >
            切到 Real
          </button>
        </div>
      </div>
    </header>

    <section class="readiness-strip" aria-label="核心状态">
      <article class="metric-card task-card">
        <div class="metric-topline">
          <span class="card-label">当前任务</span>
          <span class="status-badge" :class="toneClass(taskTone)">{{ state?.task_status.state ?? 'unknown' }}</span>
        </div>
        <strong>{{ currentTaskLabel }}</strong>
        <small>{{ state?.task_status.progress ?? 0 }}% · {{ state?.task_status.source ?? '--' }}</small>
      </article>

      <article class="metric-card">
        <div class="metric-topline">
          <span class="card-label">机器人链路</span>
          <span class="status-badge" :class="toneClass(onlineTone)">{{ connectionLabel }}</span>
        </div>
        <strong>{{ onlineStatus }}</strong>
        <small>{{ transportStatusLabel }}</small>
      </article>

      <article class="metric-card">
        <div class="metric-topline">
          <span class="card-label">电量 / 急停 / 故障</span>
          <span class="status-badge" :class="toneClass(batteryTone)">
            {{ state?.device_status.fault_code ?? (state?.device_status.emergency_stop ? 'emergency_stop' : 'normal') }}
          </span>
        </div>
        <strong>{{ batteryLabel }}</strong>
        <small>急停：{{ estopLabel }} · 更新 {{ lastUpdatedLabel }}</small>
      </article>

      <article class="metric-card">
        <div class="metric-topline">
          <span class="card-label">感知状态</span>
          <span class="status-badge" :class="toneClass(detectionTone)">{{ detectionStatusLabel }}</span>
        </div>
        <strong>{{ latestDetectionObjectLabel }}</strong>
        <small>{{ state?.detection_status?.model_name ?? '--' }}</small>
      </article>

      <article class="metric-card alert-card">
        <div class="metric-topline">
          <span class="card-label">最近告警</span>
          <span class="status-badge" :class="toneClass(latestAlertTone)">{{ latestAlert?.level ?? 'normal' }}</span>
        </div>
        <strong>{{ latestAlert?.message ?? '暂无告警' }}</strong>
        <small>{{ latestAlert ? `${latestAlert.source} · ${formatTime(latestAlert.timestamp)}` : '系统稳定' }}</small>
      </article>
    </section>

    <section class="operations-grid">
      <div class="operations-primary">
        <NavMapPlaceholder
          :robot-pose="state?.robot_pose ?? null"
          :goal="navGoal"
          :nav-state="state?.nav_status.state ?? null"
        />

        <article class="panel mission-panel">
          <div class="section-header compact-header">
            <div>
              <p class="section-kicker">Mission Control</p>
              <h2>任务快捷控制</h2>
            </div>
            <span class="hint-text">{{ actionMessage }}</span>
          </div>

          <div class="mission-form-row">
            <label class="field inline-field">
              <span>目标点 ID</span>
              <input v-model="waypointId" type="text" placeholder="例如 wp_201" />
            </label>

            <div class="button-row mission-actions">
              <button
                :disabled="isSending || !waypointId"
                type="button"
                @click="sendMission('/api/mission/go_to_waypoint', { waypoint_id: waypointId, source: 'web', requested_by: 'dashboard' }, '已发送前往目标点命令')"
              >
                前往目标点
              </button>
              <button
                :disabled="isSending"
                class="secondary"
                type="button"
                @click="sendMission('/api/mission/pause', { source: 'web', requested_by: 'dashboard' }, '已发送暂停命令')"
              >
                暂停
              </button>
              <button
                :disabled="isSending"
                class="secondary"
                type="button"
                @click="sendMission('/api/mission/resume', { source: 'web', requested_by: 'dashboard' }, '已发送恢复命令')"
              >
                恢复
              </button>
              <button
                :disabled="isSending"
                class="warn"
                type="button"
                @click="sendMission('/api/mission/return_home', { source: 'web', requested_by: 'dashboard' }, '已发送返航命令')"
              >
                返回 Home
              </button>
            </div>
          </div>
        </article>
      </div>

      <div class="operations-secondary">
        <article class="panel voice-panel">
          <div class="section-header compact-header">
            <div>
              <p class="section-kicker">Voice / LLM</p>
              <h2>语音与语义任务入口</h2>
            </div>
            <span class="voice-summary-chip" :class="toneClass(pendingVoiceCommand ? 'warning' : voiceRecordError ? 'danger' : 'info')">
              {{ latestVoiceSummary }}
            </span>
          </div>

          <div class="voice-command-stack">
            <label class="field">
              <span>文本命令</span>
              <input v-model="textCommand" type="text" placeholder="例如 帮我把样品送到二零一实验室" @keyup.enter="sendTextCommand" />
            </label>

            <div class="button-row voice-actions">
              <button :disabled="isSendingTextCommand || !textCommand.trim()" type="button" @click="sendTextCommand">
                {{ isSendingTextCommand ? '发送中...' : '发送文本命令' }}
              </button>
              <label class="field compact-field duration-field">
                <span>板端录音</span>
                <select v-model.number="voiceRecordDuration" :disabled="isRecordingVoice">
                  <option :value="2">2 秒</option>
                  <option :value="3">3 秒</option>
                  <option :value="5">5 秒</option>
                </select>
              </label>
              <button class="secondary" :disabled="isRecordingVoice" type="button" @click="recordVoiceCommand">
                {{ isRecordingVoice ? '录音识别中...' : '开始录音识别' }}
              </button>
            </div>
          </div>

          <div class="status-message-stack">
            <p v-if="isRecordingVoice" class="inline-status">正在录音并识别，请说话...</p>
            <p v-if="voiceRecordNoCommandLabel" class="inline-status warn-status">{{ voiceRecordNoCommandLabel }}</p>
            <p v-if="voiceRecordError" class="inline-status error-status">{{ voiceRecordError }}</p>
          </div>

          <div class="voice-result-grid">
            <div class="detail-item wide-detail highlight-detail">
              <span>识别文本</span>
              <strong>{{ voiceRecordResult?.recognized_text || voiceResult?.recognized_text || textCommand || '--' }}</strong>
            </div>
            <div class="detail-item">
              <span>ASR 后端</span>
              <strong>{{ voiceRecordResult?.asr_backend ?? 'text' }}</strong>
            </div>
            <div class="detail-item">
              <span>ASR 耗时</span>
              <strong>{{ formatNumber(voiceRecordResult?.asr_time_s, ' s') }}</strong>
            </div>
            <div class="detail-item">
              <span>intent</span>
              <strong>{{ voiceRecordResult?.intent ?? voiceResult?.intent ?? '--' }}</strong>
            </div>
            <div class="detail-item">
              <span>waypoint_id</span>
              <strong>{{ voiceRecordResult?.waypoint_id ?? voiceResult?.waypoint_id ?? voiceRecordResult?.payload.waypoint_id ?? voiceResult?.payload.waypoint_id ?? '--' }}</strong>
            </div>
            <div class="detail-item">
              <span>accepted / need_confirm</span>
              <strong>{{ voiceRecordResult ? voiceStatusLabel(voiceRecordResult) : voiceResult ? voiceStatusLabel(voiceResult) : '--' }}</strong>
            </div>
            <div class="detail-item">
              <span>pending_command_id</span>
              <strong>{{ pendingVoiceCommand?.pending_command_id ?? voiceRecordResult?.pending_command_id ?? voiceResult?.pending_command_id ?? '--' }}</strong>
            </div>
            <div class="detail-item">
              <span>解析方式</span>
              <strong>{{ voiceRecordResult?.parser ?? voiceResult?.parser ?? '--' }}</strong>
            </div>
            <div class="detail-item">
              <span>LLM 模型</span>
              <strong>{{ voiceRecordResult?.llm_model ?? voiceResult?.llm_model ?? '--' }}</strong>
            </div>
            <div class="detail-item wide-detail">
              <span>任务反馈</span>
              <strong>{{ voiceRecordResult?.detail || voiceRecordResult?.error || voiceResult?.detail || voiceResult?.error || '--' }}</strong>
            </div>
          </div>
        </article>

        <article class="panel perception-panel">
          <div class="section-header compact-header">
            <div>
              <p class="section-kicker">Perception</p>
              <h2>YOLO 检测状态</h2>
            </div>
            <span class="status-badge" :class="toneClass(detectionTone)">{{ detectionStatusLabel }}</span>
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

          <div class="detail-grid detection-grid">
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
              <span>更新时间</span>
              <strong>{{ state?.detection_status ? formatTime(state.detection_status.timestamp) : '--' }}</strong>
            </div>
            <div class="detail-item wide-detail">
              <span>最近事件</span>
              <strong>{{ latestDetectionEventLabel }}</strong>
            </div>
          </div>

          <div v-if="currentDetectionObjects.length || recentDetectionObjects.length" class="object-list">
            <span
              v-for="object in [...currentDetectionObjects, ...recentDetectionObjects].slice(0, 6)"
              :key="`${object.class_name}-${object.confidence}-${object.last_seen_at ?? ''}`"
              class="object-pill"
            >
              {{ object.class_name }} · {{ object.confidence.toFixed(2) }}
            </span>
          </div>
          <div v-else class="empty-state compact-empty">暂无检测对象</div>

          <div class="event-mini-list detection-event-list">
            <div v-if="detectionEventItems.length === 0" class="empty-state compact-empty">暂无视觉事件</div>
            <div
              v-for="event in detectionEventItems.slice(0, 4)"
              v-else
              :key="`${event.event_type}-${event.message}`"
              class="mini-event"
            >
              <span class="status-badge" :class="toneClass(alertTone(event.level))">{{ event.level }}</span>
              <strong>{{ event.event_type }}</strong>
              <p>{{ event.message }}</p>
            </div>
          </div>
        </article>
      </div>
    </section>

    <section class="event-grid">
      <article class="panel events-panel">
        <div class="section-header compact-header">
          <div>
            <p class="section-kicker">Events</p>
            <h2>最近事件</h2>
          </div>
          <span class="hint-text">语音 / LLM / YOLO / Mission / 系统告警</span>
        </div>

        <ul class="event-list">
          <li v-for="event in dashboardEvents" :key="event.id" class="event-item">
            <span class="event-time">{{ event.time }}</span>
            <span class="status-badge" :class="toneClass(event.tone)">{{ event.level }}</span>
            <strong>{{ event.source }}</strong>
            <p>{{ event.message }}</p>
          </li>
          <li v-if="dashboardEvents.length === 0" class="empty-state">暂无事件</li>
        </ul>
      </article>

      <article class="panel observability-panel">
        <div class="section-header compact-header">
          <div>
            <p class="section-kicker">Runtime</p>
            <h2>链路与环境</h2>
          </div>
          <span class="hint-text">IMU / 环境 / 故障</span>
        </div>

        <div class="detail-grid runtime-grid">
          <div class="detail-item">
            <span>IMU 连接</span>
            <strong>{{ imuConnectionLabel }}</strong>
          </div>
          <div class="detail-item">
            <span>IMU 更新时间</span>
            <strong>{{ imuUpdatedLabel }}</strong>
          </div>
          <div class="detail-item wide-detail">
            <span>欧拉角</span>
            <strong v-if="imu?.imu.euler_deg" class="value-block">
              yaw={{ formatNumber(imu.imu.euler_deg.yaw) }} / pitch={{ formatNumber(imu.imu.euler_deg.pitch) }} / roll={{ formatNumber(imu.imu.euler_deg.roll) }}
            </strong>
            <strong v-else>--</strong>
          </div>
          <div class="detail-item">
            <span>温度 / 湿度</span>
            <strong>{{ formatNumber(state?.env_sensor.temperature_c, ' °C') }} / {{ formatNumber(state?.env_sensor.humidity_percent, ' %') }}</strong>
          </div>
          <div class="detail-item">
            <span>环境状态</span>
            <strong>{{ state?.env_sensor.status ?? '--' }}</strong>
          </div>
          <div class="detail-item">
            <span>故障码</span>
            <strong>{{ state?.device_status.fault_code ?? '--' }}</strong>
          </div>
        </div>
      </article>
    </section>

    <VoiceConfirmDialog
      v-if="pendingVoiceCommand"
      :result="pendingVoiceCommand"
      :loading="isConfirmingVoiceCommand"
      :error="voiceConfirmError"
      @confirm="handleVoiceConfirm(true)"
      @cancel="handleVoiceConfirm(false)"
      @close="closeVoiceConfirmDialog"
    />
  </main>
</template>
