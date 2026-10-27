import { computed, reactive, ref } from 'vue'
import { apiUrl, authHeaders, wsUrl } from '../config/api'
import { levelTone } from '../labels'
import type {
  AlertEvent,
  LogLine,
  MapMetadata,
  MapPreview,
  MapUploadStatus,
  NavigationSnapshot,
  PayloadValue,
  PendingCommand,
  Point,
  RobotState,
  SmartCommandResult,
  TaskEvent,
  Tone,
  Waypoint,
} from '../types'

const TOKEN_KEY = 'qhxd_api_token'

const ERROR_CODES: Record<string, string> = {
  unauthorized: '公网写接口需要访问 Token，请在右上角设置',
  public_control_disabled: '云端已关闭公网运动控制（PUBLIC_CONTROL_ENABLED=false）',
  public_endpoint_disabled: '该接口不对公网开放',
  robot_offline: '机器人离线，命令未转发',
  robot_emergency_stop: '机器人处于急停，命令未转发',
  rate_limited: '请求过于频繁，请稍后再试',
}

async function readApiError(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string; error?: string }
    const code = payload.detail || payload.error || ''
    if (code.startsWith('robot_fault:')) return `机器人存在故障：${code.slice(12)}`
    return ERROR_CODES[code] ?? (code || fallback)
  } catch {
    return fallback
  }
}

export function useYunTuo() {
  const state = ref<RobotState | null>(null)
  const nav = ref<NavigationSnapshot | null>(null)
  const mapMeta = ref<MapMetadata | null>(null)
  const mapUpload = ref<MapUploadStatus>({ state: 'idle', detail: '选择场地的 .nvmp 地图包。' })
  const mapUploadError = ref('')
  const mapPreview = ref<MapPreview | null>(null)
  const mapUploading = computed(() => ['queued', 'uploading'].includes(mapUpload.value.state))
  let mapPollBusy = false
  let lastMapPoll = 0
  const mapImageVersion = ref('')
  const waypoints = ref<Waypoint[]>([])
  const alerts = ref<AlertEvent[]>([])
  const taskEvents = ref<TaskEvent[]>([])
  const trail = ref<Point[]>([])
  const logs = ref<LogLine[]>([])
  const token = ref(window.localStorage.getItem(TOKEN_KEY) ?? '')
  const pending = ref<PendingCommand | null>(null)
  const smart = ref<SmartCommandResult | null>(null)
  const conn = reactive({ state: false, nav: false })
  const busy = reactive({ mission: false, voice: false, confirm: false, mode: false, estop: false, map: false })
  const voiceStatus = ref('空闲')
  const confirmError = ref('')
  const lastMessage = ref('等待命令')
  const toast = ref<{ id: number; text: string; tone: Tone } | null>(null)
  let toastTimer = 0

  const platform = computed(() => state.value?.platform_status ?? null)
  const isMock = computed(() => state.value?.system_mode.mode !== 'real')
  const detections = computed(() => state.value?.detection_status?.objects ?? [])

  let stateSocket: WebSocket | null = null
  let navSocket: WebSocket | null = null
  let timers: number[] = []
  let running = false

  function log(text: string, tone: Tone = 'run', source = '控制台') {
    lastMessage.value = text
    toast.value = { id: Date.now(), text, tone }
    window.clearTimeout(toastTimer)
    toastTimer = window.setTimeout(() => { toast.value = null }, 4200)
    logs.value = [{ id: `${Date.now()}-${Math.random()}`, time: new Date().toISOString(), tone, source, text },
      ...logs.value].slice(0, 40)
  }

  async function getJson<T>(path: string): Promise<T | null> {
    try {
      const response = await fetch(apiUrl(path))
      return response.ok ? ((await response.json()) as T) : null
    } catch {
      return null
    }
  }

  async function post<T>(path: string, body: unknown, fallback: string): Promise<T> {
    const response = await fetch(apiUrl(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(body),
    })
    if (!response.ok) throw new Error(await readApiError(response, fallback))
    return (await response.json()) as T
  }

  // ------------------------------------------------------------ 数据加载
  async function loadState() {
    const payload = await getJson<{ data: RobotState }>('/api/state/latest')
    if (payload) state.value = payload.data
  }

  async function loadAlerts() {
    const payload = await getJson<{ data: AlertEvent[] }>('/api/alerts')
    if (payload) alerts.value = payload.data.slice(0, 20)
  }

  async function loadTaskEvents() {
    const payload = await getJson<{ data: TaskEvent[] }>('/api/tasks/events?limit=30')
    if (payload) taskEvents.value = payload.data
  }

  async function loadWaypoints() {
    const payload = await getJson<{ data: Waypoint[] }>('/api/waypoints')
    if (payload) waypoints.value = payload.data.filter((w) => w.enabled)
  }

  async function loadMapMeta() {
    const payload = await getJson<{ data: MapMetadata }>('/api/navigation/map/metadata')
    mapMeta.value = payload?.data ?? null
    mapImageVersion.value = payload?.data.version ?? ''
  }

  async function loadMapUpload() {
    if (mapPollBusy) return
    mapPollBusy = true
    lastMapPoll = Date.now()
    try {
      const payload = await getJson<{ data: MapUploadStatus }>('/api/navigation/map/upload')
      const preview = await getJson<{ data: MapPreview | null }>('/api/navigation/map/upload?preview=true')
      if (preview) mapPreview.value = preview.data?.version === window.sessionStorage.getItem('dismissed_map_preview') ? null : preview.data
      if (!payload) return
      const previous = mapUpload.value
      mapUpload.value = payload.data
      if (['ready', 'invalidated'].includes(payload.data.state)
          && (previous.id !== payload.data.id || previous.state !== payload.data.state)) {
        trail.value = []
        await loadMapMeta()
      }
    } finally {
      mapPollBusy = false
    }
  }

  async function uploadMap(file: File) {
    if (!file.name.toLowerCase().endsWith('.nvmp') || file.size < 48 || file.size > 86064) {
      log('请选择有效的 .nvmp 文件（48至86064字节）。', 'warn', '地图')
      return
    }
    busy.map = true
    mapUploadError.value = ''
    try {
      const query = new URLSearchParams({ filename: file.name, map_id: mapMeta.value?.map_id || 'yuntuo_field' })
      const response = await fetch(apiUrl(`/api/navigation/map/upload?${query}`), {
        method: 'POST', headers: { 'Content-Type': 'application/octet-stream', ...authHeaders() }, body: file,
      })
      if (!response.ok) throw new Error(await readApiError(response, '地图上传失败'))
      const payload = await response.json() as { data: MapUploadStatus }
      mapUpload.value = payload.data
      log('地图已提交，正在等待FPGA下发结果。', 'run', '地图')
    } catch (error) {
      const detail = error instanceof Error ? error.message : '地图上传失败'
      log(detail, 'bad', '地图')
      mapUploadError.value = detail
    } finally {
      busy.map = false
    }
  }

  async function previewMap(file: File): Promise<boolean> {
    busy.map = true
    mapUploadError.value = ''
    try {
      const query = new URLSearchParams({ filename: file.name, map_id: mapMeta.value?.map_id || 'yuntuo_field', preview: 'true' })
      const response = await fetch(apiUrl(`/api/navigation/map/upload?${query}`), {
        method: 'POST', headers: { 'Content-Type': 'application/octet-stream', ...authHeaders() }, body: file,
      })
      if (!response.ok) throw new Error(await readApiError(response, '地图预览失败'))
      mapPreview.value = (await response.json() as { data: MapPreview }).data
      window.sessionStorage.removeItem('dismissed_map_preview')
      log('地图已打开预览，尚未下发FPGA。', 'ok', '地图')
      return true
    } catch (error) {
      mapUploadError.value = error instanceof Error ? error.message : '地图预览失败'
      return false
    } finally {
      busy.map = false
    }
  }

  function dismissMapPreview() {
    if (mapPreview.value) window.sessionStorage.setItem('dismissed_map_preview', mapPreview.value.version)
    mapPreview.value = null
  }

  function pushTrail(snapshot: NavigationSnapshot) {
    const pose = snapshot.pose
    if (!pose) return
    const last = trail.value[trail.value.length - 1]
    if (last && Math.hypot(last.x - pose.x, last.y - pose.y) < 0.02) return
    if (last && Math.hypot(last.x - pose.x, last.y - pose.y) > 2.0) trail.value = []   // 跳变（重定位 / 换图）
    trail.value = [...trail.value, { x: pose.x, y: pose.y }].slice(-600)
  }

  // ------------------------------------------------------------ 实时流
  function connectState() {
    stateSocket = new WebSocket(wsUrl('/ws/state'))
    stateSocket.onopen = () => {
      conn.state = true
      void loadState()
    }
    stateSocket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as { type: string; data: RobotState }
      if (payload.type === 'robot_state') state.value = payload.data
    }
    stateSocket.onclose = () => {
      conn.state = false
      if (running) window.setTimeout(connectState, 3000)
    }
  }

  function connectNav() {
    navSocket = new WebSocket(wsUrl('/ws/navigation'))
    navSocket.onopen = () => {
      conn.nav = true
    }
    navSocket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as { type: string; data: NavigationSnapshot | null }
      if (payload.type !== 'navigation' || !payload.data) return
      nav.value = payload.data
      pushTrail(payload.data)
      if (payload.data.map_version && payload.data.map_version !== mapImageVersion.value) void loadMapMeta()
    }
    navSocket.onclose = () => {
      conn.nav = false
      if (running) window.setTimeout(connectNav, 3000)
    }
  }

  async function start() {
    running = true
    await Promise.all([loadState(), loadAlerts(), loadWaypoints(), loadMapMeta(), loadTaskEvents(), loadMapUpload()])
    connectState()
    connectNav()
    timers = [
      window.setInterval(() => void loadAlerts(), 5000),
      window.setInterval(() => void loadTaskEvents(), 3000),
      window.setInterval(() => void loadState(), 15000),
      window.setInterval(() => void loadWaypoints(), 60000),
      window.setInterval(() => {
        if (!busy.map && Date.now() - lastMapPoll >= (mapUploading.value ? 1000 : 5000)) void loadMapUpload()
      }, 1000),
    ]
  }

  function stop() {
    running = false
    stateSocket?.close()
    navSocket?.close()
    timers.forEach((t) => window.clearInterval(t))
  }

  // ------------------------------------------------------------ 任务
  type MissionResponse = { data: { accepted: boolean; detail: string } }

  async function mission(command: string, body: Record<string, PayloadValue> = {}) {
    busy.mission = true
    try {
      const payload = await post<MissionResponse>(`/api/mission/${command}`,
        { source: 'web', requested_by: 'dashboard', ...body }, '任务接口调用失败')
      log(payload.data.detail, payload.data.accepted ? 'ok' : 'warn', '任务')
      await Promise.all([loadState(), loadTaskEvents()])
    } catch (error) {
      log(error instanceof Error ? error.message : '任务发送失败', 'bad', '任务')
    } finally {
      busy.mission = false
    }
  }

  function goTo(waypointId: string) {
    return mission('go_to_waypoint', { waypoint_id: waypointId })
  }

  function searchTarget(targetClass: string, color: string | null, label: string, timeoutS = 180) {
    return mission('search_target', { target_class: targetClass, color, label, timeout_s: timeoutS })
  }

  function followMe(timeoutS = 300) {
    return mission('follow_target', { target_class: 'person', label: '我', timeout_s: timeoutS })
  }

  async function estop(engage: boolean) {
    busy.estop = true
    try {
      const payload = await post<MissionResponse>('/api/platform/estop',
        { engage, source: 'web', requested_by: 'dashboard' }, '急停接口调用失败')
      log(payload.data.detail, payload.data.accepted ? (engage ? 'bad' : 'ok') : 'warn', '急停')
    } catch (error) {
      log(error instanceof Error ? error.message : '急停发送失败', 'bad', '急停')
    } finally {
      busy.estop = false
    }
  }

  async function switchMode(mode: 'mock' | 'real') {
    busy.mode = true
    try {
      const payload = await post<MissionResponse>('/api/system/mode/switch',
        { mode, source: 'web', requested_by: 'dashboard' }, '模式切换失败')
      log(payload.data.detail, 'run', '系统')
      trail.value = []
      await Promise.all([loadState(), loadAlerts(), loadMapMeta()])
    } catch (error) {
      log(error instanceof Error ? error.message : '模式切换失败', 'bad', '系统')
    } finally {
      busy.mode = false
    }
  }

  function saveToken(value: string) {
    token.value = value.trim()
    if (token.value) window.localStorage.setItem(TOKEN_KEY, token.value)
    else window.localStorage.removeItem(TOKEN_KEY)
    log(token.value ? '访问 Token 已保存' : '访问 Token 已清除', 'run', '系统')
  }

  // ------------------------------------------------------------ 语音 / 智能助手
  type SmartResponse = { success: boolean; data: SmartCommandResult | null; error?: string | null; detail?: string | null }

  function handleSmart(payload: SmartResponse, fallback: string) {
    if (!payload.success || !payload.data) {
      const message = payload.detail || payload.error || payload.data?.error_reason || fallback
      voiceStatus.value = '失败'
      log(message, 'bad', '语音')
      return
    }
    const data = payload.data
    smart.value = data
    voiceStatus.value = '已处理'
    log(data.reply_text || data.error_reason || '智能助手已处理', data.error_reason ? 'warn' : 'run', '语音')
    const candidate = data.mission_candidate
    if (candidate?.pending_command_id) {
      confirmError.value = ''
      pending.value = {
        recognized_text: data.recognized_text, intent: data.intent, command: candidate.command,
        payload: candidate.payload, confidence: data.confidence, parser: data.parser,
        llm_backend: data.llm_backend ?? null, llm_model: data.llm_model ?? null,
        waypoint_id: candidate.payload.waypoint_id == null ? null : String(candidate.payload.waypoint_id),
        detail: data.reply_text || candidate.detail, pending_command_id: candidate.pending_command_id,
      }
    }
  }

  async function sendText(text: string) {
    if (!text.trim()) return
    busy.voice = true
    voiceStatus.value = '理解中'
    try {
      const payload = await post<SmartResponse>('/api/voice/smart_command',
        { text, source: 'dashboard-smart-text', requested_by: 'dashboard', generate_tts: true }, '智能助手调用失败')
      handleSmart(payload, '智能助手调用失败')
    } catch (error) {
      voiceStatus.value = '失败'
      log(error instanceof Error ? error.message : '文本命令发送失败', 'bad', '语音')
    } finally {
      busy.voice = false
    }
  }

  async function recordBrowser(durationS: number) {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      log('当前浏览器不支持网页麦克风录音（需要 HTTPS 或 localhost）', 'warn', '语音')
      return
    }
    busy.voice = true
    voiceStatus.value = '录音中'
    let stream: MediaStream | null = null
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg']
        .find((m) => MediaRecorder.isTypeSupported(m)) ?? ''
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const chunks: BlobPart[] = []
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data) }
      await new Promise<void>((resolve, reject) => {
        recorder.onerror = () => reject(new Error('浏览器录音失败'))
        recorder.onstop = () => resolve()
        recorder.start()
        window.setTimeout(() => recorder.state !== 'inactive' && recorder.stop(), Math.max(1, durationS) * 1000)
      })
      const type = recorder.mimeType || mime || 'audio/webm'
      const blob = new Blob(chunks, { type })
      if (!blob.size) throw new Error('没有录到有效音频')
      voiceStatus.value = '识别中'
      const form = new FormData()
      form.append('file', blob, type.includes('ogg') ? 'browser_audio.ogg' : 'browser_audio.webm')
      form.append('source', 'browser-mic')
      form.append('requested_by', 'operator')
      form.append('keep_audio', 'false')
      form.append('smart', 'true')
      const response = await fetch(apiUrl('/api/voice/browser_smart_command'), {
        method: 'POST', headers: { ...authHeaders() }, body: form,
      })
      if (!response.ok) throw new Error(await readApiError(response, '网页麦克风识别失败（本机直连时请用车载麦克风）'))
      handleSmart((await response.json()) as SmartResponse, '网页麦克风识别失败')
    } catch (error) {
      const message = error instanceof Error ? error.message : '网页麦克风识别失败'
      voiceStatus.value = '失败'
      log(/denied|Permission/.test(message) ? '浏览器麦克风权限被拒绝' : message, 'bad', '语音')
    } finally {
      stream?.getTracks().forEach((t) => t.stop())
      busy.voice = false
    }
  }

  async function recordOnboard(durationS: number) {
    busy.voice = true
    voiceStatus.value = '车载麦克风录音中'
    try {
      const payload = await post<SmartResponse>('/api/robot/voice/onboard_smart_command',
        { duration: durationS, source: 'web-onboard-mic', requested_by: 'operator', keep_audio: false, smart: true },
        '车载麦克风识别失败')
      handleSmart(payload, '车载麦克风识别失败')
    } catch (error) {
      voiceStatus.value = '失败'
      log(error instanceof Error ? error.message : '车载麦克风识别失败', 'bad', '语音')
    } finally {
      busy.voice = false
    }
  }

  async function confirm(confirmed: boolean) {
    const id = pending.value?.pending_command_id
    if (!id || busy.confirm) return
    busy.confirm = true
    confirmError.value = ''
    try {
      const payload = await post<{ data: { accepted: boolean; detail: string } }>('/api/voice/confirm_command',
        { pending_command_id: id, confirmed, requested_by: 'dashboard' }, '确认请求失败')
      log(payload.data.detail || (confirmed ? '任务已确认执行' : '任务已取消'),
        confirmed && payload.data.accepted ? 'ok' : 'warn', '语音')
      pending.value = null
      await Promise.all([loadState(), loadTaskEvents()])
    } catch (error) {
      confirmError.value = error instanceof Error ? error.message : '确认请求失败'
    } finally {
      busy.confirm = false
    }
  }

  const timeline = computed<LogLine[]>(() => {
    const events = taskEvents.value.map((e) => ({
      id: `t-${e.event_id}`, time: e.timestamp, tone: levelTone(e.event_type), source: '任务', text: e.detail,
    }))
    const alertLines = alerts.value.filter((a) => a.source !== 'mock-state-generator').map((a) => ({
      id: `a-${a.alert_id}`, time: a.timestamp, tone: levelTone(a.level), source: a.source, text: a.message,
    }))
    return [...events, ...alertLines, ...logs.value]
      .sort((a, b) => Date.parse(b.time) - Date.parse(a.time))
      .slice(0, 60)
  })

  return {
    state, nav, mapMeta, mapPreview, mapImageVersion, mapUpload, mapUploadError, mapUploading, waypoints, alerts, taskEvents, trail, logs, token, pending, smart, conn, busy,
    voiceStatus, confirmError, lastMessage, toast, platform, isMock, detections, timeline,
    start, stop, mission, goTo, searchTarget, followMe, estop, switchMode, saveToken, sendText, recordBrowser,
    recordOnboard, confirm, uploadMap, previewMap, dismissMapPreview, log,
  }
}

export type YunTuo = ReturnType<typeof useYunTuo>
