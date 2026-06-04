<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import NavMapPlaceholder from './components/NavMapPlaceholder.vue'
import NavigationAssistPanel from './components/NavigationAssistPanel.vue'
import VoiceConfirmDialog from './components/VoiceConfirmDialog.vue'
import {
  ENABLE_LOCAL_RECORD_COMMAND,
  apiUrl,
  authHeaders,
  perceptionFrameStreamUrl,
  perceptionLatestFrameUrl,
  wsUrl,
} from './config/api'

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
  raw_text?: string | null
  asr_backend?: string
  asr_time_s?: number | null
  model_load_time_s?: number | null
  audio_path?: string | null
  duration?: number
  audio_device?: string
  audio_retained?: boolean
}

type VoiceRecordCommandResponse = {
  success: boolean
  data: VoiceRecordCommandResult | null
  error: string | null
  detail: string | null
}

type SmartTtsStatus = {
  backend: string
  status: string
  text?: string | null
  audio_path?: string | null
  detail?: string | null
  updated_at?: string | null
}

type SmartCommandResult = {
  request_id: string
  recognized_text: string
  intent: string | null
  data_source: string | null
  reply_text: string
  need_confirm: boolean
  mission_candidate: {
    command: string
    payload: Record<string, VoicePayloadValue>
    pending_command_id: string | null
    detail: string
  } | null
  pending_command_id: string | null
  tts_status: SmartTtsStatus | null
  error_reason: string | null
  confidence: number
  parser: string
  llm_backend?: string | null
  llm_model?: string | null
  timestamp: string
}

type SmartCommandResponse = {
  success: boolean
  data: SmartCommandResult
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

type DetectionEventItem = DetectionStatus['events'][number] & {
  id: string
  time: string
  first_seen_at: number
  expires_at: number
}

const state = ref<RobotState | null>(null)
const alerts = ref<AlertEvent[]>([])
const imu = ref<ImuEnvelope | null>(null)
const waypointId = ref('mock-waypoint')
const textCommand = ref('去一号点')
const voiceResult = ref<VoiceCommandResponse['data'] | null>(null)
const voiceRecordResult = ref<VoiceRecordCommandResult | null>(null)
const smartCommandResult = ref<SmartCommandResult | null>(null)
const voiceRecordError = ref('')
const voiceRecordStatus = ref('空闲')
const voiceRecordDuration = ref(3)
const pendingVoiceCommand = ref<VoiceCommandResult | null>(null)
const pendingVoiceSource = ref<'text' | 'record' | null>(null)
const voiceConfirmError = ref('')
const connectionLabel = ref('连接中')
const imuConnectionLabel = ref('IMU 流连接中')
const actionMessage = ref('等待命令')
const apiTokenInput = ref(window.localStorage.getItem('qhxd_api_token') ?? '')
const apiTokenSaved = ref(Boolean(apiTokenInput.value.trim()))
const isSending = ref(false)
const isSendingTextCommand = ref(false)
const isSendingSmartCommand = ref(false)
const isRecordingVoice = ref(false)
const isBrowserVoiceRecording = ref(false)
const isOnboardVoiceRecording = ref(false)
const isConfirmingVoiceCommand = ref(false)
const isSwitchingMode = ref(false)
const wsConnected = ref(false)
const imuWsConnected = ref(false)
const shouldReconnect = ref(true)
const latestFrameUrl = ref('')
const latestFrameAvailable = ref(false)
const currentClockLabel = ref('--')
const detectionEventHistory = ref<DetectionEventItem[]>([])

let socket: WebSocket | null = null
let imuSocket: WebSocket | null = null
let alertsTimer: number | null = null
let stateTimer: number | null = null
let latestFrameTimer: number | null = null
let clockTimer: number | null = null

function getLatestFrameRefreshIntervalMs(): number {
  const rawValue = import.meta.env.VITE_LATEST_FRAME_INTERVAL_MS
  const intervalMs = Number(rawValue)
  if (!Number.isFinite(intervalMs)) {
    return 2000
  }
  return Math.max(200, intervalMs)
}

function getEnvBool(name: string, defaultValue: boolean): boolean {
  const rawValue = import.meta.env[name]
  if (rawValue === undefined || rawValue === '') {
    return defaultValue
  }
  return ['1', 'true', 'yes', 'on'].includes(String(rawValue).toLowerCase())
}

function getEnvNumber(name: string, defaultValue: number, minValue: number): number {
  const value = Number(import.meta.env[name])
  if (!Number.isFinite(value)) {
    return defaultValue
  }
  return Math.max(minValue, value)
}

const latestFrameRefreshIntervalMs = getLatestFrameRefreshIntervalMs()
const useMjpegFrameStream = getEnvBool('VITE_USE_MJPEG_STREAM', true)
const detectionEventHoldMs = getEnvNumber('VITE_DETECTION_EVENT_HOLD_MS', 15000, 1000)
const detectionEventMaxItems = Math.floor(getEnvNumber('VITE_DETECTION_EVENT_MAX_ITEMS', 12, 1))
const enableLocalRecordCommand = ENABLE_LOCAL_RECORD_COMMAND
const apiAuthLabel = computed(() => (apiTokenSaved.value ? '公网 Token 已保存' : '公网 Token 未设置'))
const isAnyVoiceRecording = computed(() => isRecordingVoice.value || isBrowserVoiceRecording.value || isOnboardVoiceRecording.value)

const onlineStatus = computed(() => {
  if (!state.value) {
    return '未连接'
  }

  if (state.value.system_mode.mode === 'mock') {
    return wsConnected.value ? '在线（Mock）' : '离线（Mock）'
  }

  if (state.value.device_status.fault_code === 'waiting-for-real-state') {
    return '等待 Navi'
  }

  if (state.value.device_status.fault_code === 'nuc-state-timeout') {
    return 'Navi 状态超时'
  }

  if (state.value.device_status.fault_code === 'nuc-bridge-unreachable') {
    return 'Navi Link 离线'
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
    return '已切到 real，等待 Navi 首包'
  }

  if (state.value.device_status.fault_code === 'nuc-state-timeout') {
    return 'Navi 状态超时，等待恢复'
  }

  if (state.value.device_status.fault_code === 'nuc-bridge-unreachable') {
    return 'Navi 命令链路异常'
  }

  return 'Navi real link 已连接'
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
  const event = detectionEventHistory.value[0]
  return event ? `${event.event_type} · ${event.message}` : 'no event'
})

const detectionEventItems = computed(() => detectionEventHistory.value)

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

const navTone = computed<StatusTone>(() => {
  const navState = state.value?.nav_status.state?.toLowerCase() ?? ''
  if (!navState || navState === 'idle' || navState === 'waiting') {
    return 'muted'
  }
  if (navState.includes('running') || navState.includes('navigating') || navState.includes('active')) {
    return 'info'
  }
  if (navState.includes('pause') || navState.includes('pending')) {
    return 'warning'
  }
  if (navState.includes('fail') || navState.includes('error') || navState.includes('lost')) {
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


watch(
  () => state.value?.detection_status,
  (detection) => {
    rememberDetectionEvents(detection ?? null)
  },
)

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

  detectionEventItems.value.slice(0, 4).forEach((event) => {
    items.push({
      id: event.id,
      time: event.time,
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

const navigationAssistVoiceText = computed(() => {
  return voiceRecordResult.value?.recognized_text || voiceResult.value?.recognized_text || null
})

const navigationAssistLlmTarget = computed(() => {
  return voiceRecordResult.value?.waypoint_id
    ?? voiceResult.value?.waypoint_id
    ?? valueAsString(voiceRecordResult.value?.payload?.waypoint_id)
    ?? valueAsString(voiceResult.value?.payload?.waypoint_id)
    ?? null
})

const navigationAssistConfirmationState = computed(() => {
  if (pendingVoiceCommand.value) {
    return '待确认'
  }

  const latest = voiceRecordResult.value ?? voiceResult.value
  return latest ? voiceStatusLabel(latest) : null
})

const voiceRecordStatusHint = computed(() => {
  if (isBrowserVoiceRecording.value) {
    return '网页麦克风录音识别中'
  }

  if (isOnboardVoiceRecording.value) {
    return '车载麦克风录音识别中'
  }

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
  const response = await fetch(apiUrl('/api/voice/confirm_command'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
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
  if (useMjpegFrameStream) {
    startLatestFrameStream()
  } else {
    startLatestFramePolling()
  }
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
    const response = await fetch(apiUrl('/api/state/latest'))
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
    const response = await fetch(apiUrl('/api/alerts'))
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
    const response = await fetch(apiUrl('/api/imu/latest'))
    if (!response.ok) {
      throw new Error('IMU 接口不可用')
    }

    const payload = (await response.json()) as ImuResponse
    imu.value = payload.data
  } catch {
    imu.value = null
  }
}

function startLatestFrameStream() {
  latestFrameAvailable.value = true
  latestFrameUrl.value = perceptionFrameStreamUrl()
}

function startLatestFramePolling() {
  refreshLatestFrame()
  if (latestFrameTimer === null) {
    latestFrameTimer = window.setInterval(refreshLatestFrame, latestFrameRefreshIntervalMs)
  }
}

function refreshLatestFrame() {
  latestFrameAvailable.value = true
  latestFrameUrl.value = perceptionLatestFrameUrl()
}

function handleLatestFrameError() {
  latestFrameAvailable.value = false
  if (useMjpegFrameStream && latestFrameTimer === null) {
    window.setTimeout(startLatestFramePolling, 500)
  }
}

function handleLatestFrameLoad() {
  latestFrameAvailable.value = true
}

function connectWebSocket() {
  socket = new WebSocket(wsUrl('/ws/state'))

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
  imuSocket = new WebSocket(wsUrl('/ws/imu'))

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
    const response = await fetch(apiUrl(path), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
      },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      throw new Error(await readApiError(response, '任务接口调用失败'))
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
    const response = await fetch(apiUrl('/api/voice/text_command'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
      },
      body: JSON.stringify({
        text: textCommand.value,
        source: 'dashboard-text',
        requested_by: 'dashboard',
      }),
    })
    if (!response.ok) {
      throw new Error(await readApiError(response, '文本命令接口调用失败'))
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

async function sendSmartCommand() {
  if (!textCommand.value.trim()) {
    smartCommandResult.value = null
    actionMessage.value = '请输入智能助手文本'
    return
  }

  isSendingSmartCommand.value = true

  try {
    const response = await fetch(apiUrl('/api/voice/smart_command'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
      },
      body: JSON.stringify({
        text: textCommand.value,
        source: 'dashboard-smart',
        requested_by: 'dashboard',
        generate_tts: true,
      }),
    })
    if (!response.ok) {
      throw new Error(await readApiError(response, '智能助手接口调用失败'))
    }

    const payload = (await response.json()) as SmartCommandResponse
    smartCommandResult.value = payload.data
    actionMessage.value = payload.data.reply_text || payload.data.error_reason || '智能助手已处理'

    if (payload.data.mission_candidate?.pending_command_id) {
      const candidate = payload.data.mission_candidate
      handleVoiceCommandResult(
        {
          accepted: false,
          intent: payload.data.intent,
          command: candidate.command,
          payload: candidate.payload,
          confidence: payload.data.confidence,
          need_confirm: true,
          pending_command_id: candidate.pending_command_id,
          recognized_text: payload.data.recognized_text,
          waypoint_id: valueAsString(candidate.payload.waypoint_id),
          parser: payload.data.parser,
          llm_backend: payload.data.llm_backend ?? null,
          llm_model: payload.data.llm_model ?? null,
          detail: payload.data.reply_text,
          task_status: null,
        },
        'text',
        payload.data.recognized_text,
      )
    } else {
      pendingVoiceCommand.value = null
      voiceConfirmError.value = ''
    }

    await Promise.all([loadState(), loadAlerts()])
  } catch (error) {
    const message = error instanceof Error ? error.message : '智能助手请求失败'
    actionMessage.value = message
    smartCommandResult.value = {
      request_id: '',
      recognized_text: textCommand.value,
      intent: null,
      data_source: null,
      reply_text: '',
      need_confirm: false,
      mission_candidate: null,
      pending_command_id: null,
      tts_status: null,
      error_reason: message,
      confidence: 0,
      parser: 'frontend',
      timestamp: new Date().toISOString(),
    }
  } finally {
    isSendingSmartCommand.value = false
  }
}

async function recordVoiceCommand() {
  if (!enableLocalRecordCommand) {
    voiceRecordError.value = '公网模式不提供板端录音，请使用浏览器/小程序录音上传。'
    voiceRecordStatus.value = '公网禁用'
    actionMessage.value = voiceRecordError.value
    return
  }

  if (isRecordingVoice.value) {
    return
  }

  isRecordingVoice.value = true
  voiceRecordStatus.value = '录音识别中'
  voiceRecordError.value = ''
  voiceRecordResult.value = null

  try {
    const response = await fetch(apiUrl('/api/voice/record_command'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
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

function preferredBrowserAudioMimeType() {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/ogg',
  ]
  if (typeof MediaRecorder === 'undefined') {
    return ''
  }
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate)) ?? ''
}

function browserAudioFilename(mimeType: string) {
  if (mimeType.includes('ogg')) {
    return 'browser_audio.ogg'
  }
  return 'browser_audio.webm'
}

async function uploadVoiceFormData(path: string, formData: FormData, fallback: string) {
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    headers: {
      ...authHeaders(),
    },
    body: formData,
  })
  if (!response.ok) {
    throw new Error(await readApiError(response, fallback))
  }
  return (await response.json()) as VoiceRecordCommandResponse
}

async function handleVoiceResponsePayload(payload: VoiceRecordCommandResponse | null, fallback: string) {
  if (!payload?.success) {
    voiceRecordResult.value = payload?.data ?? null
    const message = payload?.detail || payload?.error || payload?.data?.error || fallback
    voiceRecordError.value = message
    voiceRecordStatus.value = '失败'
    actionMessage.value = message
    return
  }

  if (!payload.data) {
    throw new Error('语音接口未返回识别结果')
  }

  handleVoiceCommandResult(payload.data, 'record')
  if (!shouldOpenVoiceConfirm(payload.data)) {
    await Promise.all([loadState(), loadAlerts()])
  }
}

async function recordBrowserVoiceCommand() {
  if (isAnyVoiceRecording.value) {
    return
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    voiceRecordError.value = '当前浏览器不支持网页麦克风录音'
    voiceRecordStatus.value = '失败'
    actionMessage.value = voiceRecordError.value
    return
  }

  isBrowserVoiceRecording.value = true
  voiceRecordStatus.value = '网页麦克风录音中'
  voiceRecordError.value = ''
  voiceRecordResult.value = null

  let stream: MediaStream | null = null
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = preferredBrowserAudioMimeType()
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    const chunks: BlobPart[] = []

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunks.push(event.data)
      }
    }

    await new Promise<void>((resolve, reject) => {
      recorder.onerror = () => reject(new Error('浏览器录音失败'))
      recorder.onstop = () => resolve()
      recorder.start()
      window.setTimeout(() => {
        if (recorder.state !== 'inactive') {
          recorder.stop()
        }
      }, Math.max(1, voiceRecordDuration.value) * 1000)
    })

    const effectiveMimeType = recorder.mimeType || mimeType || 'audio/webm'
    const audioBlob = new Blob(chunks, { type: effectiveMimeType })
    if (!audioBlob.size) {
      throw new Error('网页麦克风没有录到有效音频')
    }

    voiceRecordStatus.value = '网页麦克风上传识别中'
    const formData = new FormData()
    formData.append('file', audioBlob, browserAudioFilename(effectiveMimeType))
    formData.append('source', 'browser-mic')
    formData.append('requested_by', 'operator')
    formData.append('keep_audio', 'false')

    const payload = await uploadVoiceFormData(
      '/api/voice/browser_audio_command',
      formData,
      '网页麦克风识别失败',
    )
    await handleVoiceResponsePayload(payload, '网页麦克风识别失败')
  } catch (error) {
    const message = error instanceof Error ? error.message : '网页麦克风识别失败'
    voiceRecordError.value = message.includes('Permission') || message.includes('denied')
      ? '浏览器麦克风权限被拒绝'
      : message
    voiceRecordStatus.value = '失败'
    actionMessage.value = voiceRecordError.value
  } finally {
    stream?.getTracks().forEach((track) => track.stop())
    isBrowserVoiceRecording.value = false
  }
}

async function recordOnboardVoiceCommand() {
  if (isAnyVoiceRecording.value) {
    return
  }

  isOnboardVoiceRecording.value = true
  voiceRecordStatus.value = '车载麦克风录音中'
  voiceRecordError.value = ''
  voiceRecordResult.value = null

  try {
    const response = await fetch(apiUrl('/api/robot/voice/onboard_record_command'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
      },
      body: JSON.stringify({
        duration: voiceRecordDuration.value,
        source: 'web-onboard-mic',
        requested_by: 'operator',
        keep_audio: true,
      }),
    })
    if (!response.ok) {
      throw new Error(await readApiError(response, '车载麦克风识别失败'))
    }

    const payload = (await response.json()) as VoiceRecordCommandResponse
    await handleVoiceResponsePayload(payload, '车载麦克风识别失败')
  } catch (error) {
    const message = error instanceof Error ? error.message : '车载麦克风识别失败'
    voiceRecordError.value = message
    voiceRecordStatus.value = '失败'
    actionMessage.value = message
  } finally {
    isOnboardVoiceRecording.value = false
  }
}

async function switchMode(mode: 'mock' | 'real') {
  isSwitchingMode.value = true

  try {
    const response = await fetch(apiUrl('/api/system/mode/switch'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
      },
      body: JSON.stringify({
        mode,
        source: 'web',
        requested_by: 'dashboard',
      }),
    })
    if (!response.ok) {
      throw new Error(await readApiError(response, '模式切换失败'))
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
  pruneDetectionEventHistory()
}

function rememberDetectionEvents(detection: DetectionStatus | null) {
  if (!detection?.events.length) {
    pruneDetectionEventHistory()
    return
  }

  const now = Date.now()
  const eventTime = formatTime(detection.timestamp)
  const history = [...detectionEventHistory.value]

  detection.events.forEach((event, index) => {
    const key = detectionEventKey(event)
    const existingIndex = history.findIndex((item) => detectionEventKey(item) === key)
    const existing = existingIndex >= 0 ? history.splice(existingIndex, 1)[0] : null
    history.unshift({
      ...event,
      id: existing?.id ?? `detection-${now}-${index}-${event.event_type}`,
      time: eventTime,
      first_seen_at: existing?.first_seen_at ?? now,
      expires_at: now + detectionEventHoldMs,
    })
  })

  detectionEventHistory.value = history
    .filter((item) => item.expires_at > now)
    .sort((left, right) => right.expires_at - left.expires_at)
    .slice(0, detectionEventMaxItems)
}

function pruneDetectionEventHistory() {
  const now = Date.now()
  detectionEventHistory.value = detectionEventHistory.value.filter((event) => event.expires_at > now)
}

function detectionEventKey(event: Pick<DetectionEventItem, 'event_type' | 'level' | 'message'>) {
  return `${event.event_type}|${event.level}|${event.message}`
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

async function readApiError(response: Response, fallback: string) {
  try {
    const payload = await response.json() as { detail?: string; error?: string }
    const code = payload.detail || payload.error
    if (code === 'unauthorized') {
      return '公网写接口需要 Token，请先在顶部保存访问 Token'
    }
    if (code === 'public_control_disabled') {
      return '云端 PUBLIC_CONTROL_ENABLED=false，移动类控制已被安全开关拦截'
    }
    if (code === 'public_endpoint_disabled') {
      return '该接口不对公网开放'
    }
    if (code === 'robot_offline') {
      return '机器人离线，命令未转发'
    }
    if (code === 'ffmpeg_not_installed') {
      return '云服务器未安装 ffmpeg，无法转码浏览器录音'
    }
    if (code === 'ffmpeg_transcode_failed') {
      return payload.detail || '浏览器录音转码失败'
    }
    if (code === 'unsupported_audio_type') {
      return payload.detail || '浏览器录音格式不受支持'
    }
    if (code === 'browser_audio_too_large') {
      return '浏览器录音文件过大'
    }
    if (code === 'browser_audio_too_long') {
      return '浏览器录音时间过长'
    }
    if (code?.startsWith('robot_fault:')) {
      return `机器人故障状态，命令未执行：${code.replace('robot_fault:', '')}`
    }
    return code || fallback
  } catch {
    return fallback
  }
}

function saveApiToken() {
  const token = apiTokenInput.value.trim()
  if (token) {
    window.localStorage.setItem('qhxd_api_token', token)
    apiTokenSaved.value = true
    actionMessage.value = '公网 Token 已保存，写接口将携带 Authorization'
    return
  }

  window.localStorage.removeItem('qhxd_api_token')
  apiTokenSaved.value = false
  actionMessage.value = '公网 Token 已清除'
}
</script>

<template>
  <main class="dashboard">
    <header class="command-header">
      <div class="brand-block">
        <p class="eyebrow">Qionghai Xindong Robot Console</p>
        <h1>灵巡车载机器人中台</h1>
        <p class="header-subtitle">「灵巡 · SENTINEL」 车载交互与状态中枢</p>
      </div>

      <div class="header-control-plane">
        <div class="top-status-items" aria-label="系统状态">
          <span class="status-badge mode-badge" :class="toneClass(state?.system_mode.mode === 'real' ? 'info' : 'muted')">
            {{ systemModeLabel }} 模式
          </span>
          <span class="status-badge" :class="toneClass(onlineTone)">Navi {{ onlineStatus }}</span>
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

        <div class="public-auth-control" aria-label="公网写接口鉴权">
          <span class="status-badge" :class="toneClass(apiTokenSaved ? 'success' : 'warning')">
            {{ apiAuthLabel }}
          </span>
          <input
            v-model="apiTokenInput"
            type="password"
            autocomplete="off"
            placeholder="输入公网 Token"
            @keyup.enter="saveApiToken"
          />
          <button class="secondary compact-button" type="button" @click="saveApiToken">
            保存 Token
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

      <article class="metric-card nav-status-card">
        <div class="metric-topline">
          <span class="card-label">导航状态</span>
          <span class="status-badge" :class="toneClass(navTone)">{{ state?.nav_status.state ?? 'unknown' }}</span>
        </div>
        <strong>{{ state?.nav_status.current_goal ?? state?.task_status.task_id ?? '未设置目标' }}</strong>
        <small>剩余距离：{{ formatNumber(state?.nav_status.remaining_distance, ' m') }} · {{ state?.nav_status.mode ?? '--' }}</small>
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

        <NavigationAssistPanel
          :task-status="state?.task_status ?? null"
          :nav-status="state?.nav_status ?? null"
          :robot-pose="state?.robot_pose ?? null"
          :device-status="state?.device_status ?? null"
          :system-mode="state?.system_mode.mode ?? null"
          :alerts="alerts"
          :updated-at="state?.updated_at ?? null"
          :ws-connected="wsConnected"
          :imu-ws-connected="imuWsConnected"
          :connection-label="connectionLabel"
          :imu-connection-label="imuConnectionLabel"
          :voice-text="navigationAssistVoiceText"
          :llm-target="navigationAssistLlmTarget"
          :confirmation-state="navigationAssistConfirmationState"
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
      </div>

      <div class="operations-secondary">
        <article class="panel voice-panel command-palette-panel">
          <div class="section-header compact-header">
            <div>
              <p class="section-kicker">Command Palette</p>
              <h2>语音 / LLM 命令面板</h2>
            </div>
            <span class="voice-summary-chip" :class="toneClass(pendingVoiceCommand ? 'warning' : voiceRecordError ? 'danger' : 'info')">
              {{ pendingVoiceCommand ? '移动任务待确认' : voiceRecordStatusHint }}
            </span>
          </div>

          <div class="command-input-shell">
            <label class="field command-field">
              <span>输入任务命令</span>
              <input v-model="textCommand" type="text" placeholder="例如 帮我把样品送到二零一实验室" @keyup.enter="sendTextCommand" />
            </label>
            <div class="command-actions">
              <button :disabled="isSendingTextCommand || !textCommand.trim()" type="button" @click="sendTextCommand">
                {{ isSendingTextCommand ? '发送中...' : '发送文本命令' }}
              </button>
              <button class="accent" :disabled="isSendingSmartCommand || !textCommand.trim()" type="button" @click="sendSmartCommand">
                {{ isSendingSmartCommand ? '思考中...' : '智能助手解析' }}
              </button>
              <label class="field compact-field duration-field">
                <span>录音时长</span>
                <select v-model.number="voiceRecordDuration" :disabled="isAnyVoiceRecording">
                  <option :value="2">2 秒</option>
                  <option :value="3">3 秒</option>
                  <option :value="5">5 秒</option>
                </select>
              </label>
              <button
                class="secondary"
                :disabled="isAnyVoiceRecording"
                type="button"
                title="使用当前浏览器、手机或电脑的麦克风录音并上传云端转码"
                @click="recordBrowserVoiceCommand"
              >
                {{ isBrowserVoiceRecording ? '网页麦克风识别中...' : '网页麦克风识别' }}
              </button>
              <button
                class="secondary"
                :disabled="isAnyVoiceRecording"
                type="button"
                title="通过云端安全接口触发机器人 RK3588 上的 USB 麦克风录音"
                @click="recordOnboardVoiceCommand"
              >
                {{ isOnboardVoiceRecording ? '车载麦克风录音中...' : '车载麦克风识别' }}
              </button>
              <button
                v-if="enableLocalRecordCommand"
                class="secondary"
                :disabled="isAnyVoiceRecording"
                type="button"
                @click="recordVoiceCommand"
              >
                {{ isRecordingVoice ? '录音识别中...' : '开始录音识别' }}
              </button>
            </div>
          </div>

          <section class="smart-assistant-card" aria-label="灵巡 Sentinel 智能语音助手">
            <div class="smart-assistant-head">
              <div>
                <p class="section-kicker">Lingxun Sentinel</p>
                <h3>灵巡 Sentinel 智能语音助手</h3>
              </div>
              <span class="status-badge" :class="toneClass(smartCommandResult?.error_reason ? 'danger' : smartCommandResult ? 'info' : 'muted')">
                {{ smartCommandResult?.error_reason ? 'rejected' : smartCommandResult ? 'ready' : 'waiting' }}
              </span>
            </div>
            <div class="smart-reply">
              <span>回复</span>
              <strong>{{ smartCommandResult?.reply_text || '等待智能语音交互' }}</strong>
            </div>
            <div class="command-meta-grid smart-meta-grid">
              <div>
                <span>recognized_text</span>
                <strong>{{ smartCommandResult?.recognized_text || '--' }}</strong>
              </div>
              <div>
                <span>intent</span>
                <strong>{{ smartCommandResult?.intent || '--' }}</strong>
              </div>
              <div>
                <span>data_source</span>
                <strong>{{ smartCommandResult?.data_source || '--' }}</strong>
              </div>
              <div>
                <span>TTS</span>
                <strong>{{ smartCommandResult?.tts_status?.status || '--' }}</strong>
              </div>
              <div>
                <span>mission_candidate</span>
                <strong>{{ smartCommandResult?.mission_candidate?.command || '--' }}</strong>
              </div>
              <div>
                <span>error_reason</span>
                <strong>{{ smartCommandResult?.error_reason || '--' }}</strong>
              </div>
            </div>
          </section>

          <div class="status-message-stack">
            <p v-if="isBrowserVoiceRecording" class="inline-status">正在使用当前浏览器麦克风录音，请说话...</p>
            <p v-if="isOnboardVoiceRecording" class="inline-status">正在触发机器人车载麦克风录音，请靠近机器人说话...</p>
            <p v-if="isRecordingVoice" class="inline-status">正在使用 RK3588 本地录音接口识别，请说话...</p>
            <p v-if="voiceRecordNoCommandLabel" class="inline-status warn-status">{{ voiceRecordNoCommandLabel }}</p>
            <p v-if="voiceRecordError" class="inline-status error-status">{{ voiceRecordError }}</p>
          </div>

          <section class="command-result-card" aria-label="最近命令解析结果">
            <div class="command-result-main">
              <span>最近识别</span>
              <strong>{{ voiceRecordResult?.recognized_text || voiceResult?.recognized_text || textCommand || '--' }}</strong>
            </div>
            <div class="command-result-status">
              <span class="status-badge" :class="toneClass(pendingVoiceCommand ? 'warning' : voiceRecordError ? 'danger' : voiceRecordResult || voiceResult ? 'info' : 'muted')">
                {{ voiceRecordResult ? voiceStatusLabel(voiceRecordResult) : voiceResult ? voiceStatusLabel(voiceResult) : 'waiting' }}
              </span>
            </div>
          </section>

          <div class="command-meta-grid">
            <div>
              <span>intent</span>
              <strong>{{ voiceRecordResult?.intent ?? voiceResult?.intent ?? '--' }}</strong>
            </div>
            <div>
              <span>waypoint</span>
              <strong>{{ voiceRecordResult?.waypoint_id ?? voiceResult?.waypoint_id ?? voiceRecordResult?.payload.waypoint_id ?? voiceResult?.payload.waypoint_id ?? '--' }}</strong>
            </div>
            <div>
              <span>confirm</span>
              <strong>{{ pendingVoiceCommand ? 'need_confirm' : voiceRecordResult?.need_confirm || voiceResult?.need_confirm ? 'pending' : '--' }}</strong>
            </div>
            <div>
              <span>feedback</span>
              <strong>{{ voiceRecordResult?.detail || voiceRecordResult?.error || voiceResult?.detail || voiceResult?.error || '--' }}</strong>
            </div>
          </div>

          <details class="debug-disclosure">
            <summary>ASR / LLM 调试详情</summary>
            <div class="debug-detail-grid">
              <div><span>ASR 后端</span><strong>{{ voiceRecordResult?.asr_backend ?? 'text' }}</strong></div>
              <div><span>ASR 耗时</span><strong>{{ formatNumber(voiceRecordResult?.asr_time_s, ' s') }}</strong></div>
              <div><span>parser</span><strong>{{ voiceRecordResult?.parser ?? voiceResult?.parser ?? '--' }}</strong></div>
              <div><span>LLM 模型</span><strong>{{ voiceRecordResult?.llm_model ?? voiceResult?.llm_model ?? '--' }}</strong></div>
              <div class="wide-detail"><span>pending_command_id</span><strong>{{ pendingVoiceCommand?.pending_command_id ?? voiceRecordResult?.pending_command_id ?? voiceResult?.pending_command_id ?? '--' }}</strong></div>
            </div>
          </details>
        </article>

        <article class="panel perception-panel perception-monitor-panel">
          <div class="section-header compact-header">
            <div>
              <p class="section-kicker">Perception Monitor</p>
              <h2>YOLO 感知监视器</h2>
            </div>
            <span class="status-badge" :class="toneClass(detectionTone)">{{ detectionStatusLabel }}</span>
          </div>

          <div class="latest-frame-box monitor-frame">
            <img
              v-if="latestFrameAvailable && latestFrameUrl"
              :src="latestFrameUrl"
              alt="最新识别画面"
              @error="handleLatestFrameError"
              @load="handleLatestFrameLoad"
            />
            <div v-else class="latest-frame-placeholder">暂无识别画面</div>
          </div>

          <div class="monitor-meta-strip">
            <div><span>source</span><strong>{{ state?.detection_status?.source ?? '--' }}</strong></div>
            <div><span>model</span><strong>{{ state?.detection_status?.model_name ?? '--' }}</strong></div>
            <div><span>updated</span><strong>{{ state?.detection_status ? formatTime(state.detection_status.timestamp) : '--' }}</strong></div>
          </div>

          <div class="perception-monitor-grid">
            <section class="monitor-list-card">
              <div class="monitor-list-header">
                <span>Objects</span>
                <strong>{{ currentDetectionObjects.length + recentDetectionObjects.length }}</strong>
              </div>
              <div v-if="currentDetectionObjects.length || recentDetectionObjects.length" class="object-list monitor-object-list">
                <span
                  v-for="object in [...currentDetectionObjects, ...recentDetectionObjects].slice(0, 8)"
                  :key="`${object.class_name}-${object.confidence}-${object.last_seen_at ?? ''}`"
                  class="object-pill"
                >
                  {{ object.class_name }} · {{ object.confidence.toFixed(2) }}
                </span>
              </div>
              <div v-else class="empty-state compact-empty">暂无检测对象</div>
              <div class="monitor-summary-row">
                <span>当前</span><strong>{{ currentDetectionLabel }}</strong>
                <span>最近</span><strong>{{ recentDetectionLabel }}</strong>
              </div>
            </section>

            <section class="monitor-list-card">
              <div class="monitor-list-header">
                <span>Events</span>
                <strong>{{ detectionEventItems.length }}</strong>
              </div>
              <div class="event-mini-list detection-event-list">
                <div v-if="detectionEventItems.length === 0" class="empty-state compact-empty">暂无视觉事件</div>
                <div
                  v-for="event in detectionEventItems.slice(0, 5)"
                  v-else
                  :key="event.id"
                  class="mini-event"
                >
                  <span class="status-badge" :class="toneClass(alertTone(event.level))">{{ event.level }}</span>
                  <strong>{{ event.event_type }}</strong>
                  <p>{{ event.message }}</p>
                  <small>{{ event.time }}</small>
                </div>
              </div>
              <div class="monitor-summary-row">
                <span>最近事件</span><strong>{{ latestDetectionEventLabel }}</strong>
              </div>
            </section>
          </div>
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
      </div>
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
