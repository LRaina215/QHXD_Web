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
  PatrolRoute,
  RobotState,
  SmartCommandResult,
  TaskEvent,
  Tone,
  Waypoint,
} from '../types'

const TOKEN_KEY = 'qhxd_api_token'
const VOICE_TIMEOUT_MS = 120000
const VOICE_TIMEOUT_MESSAGE = '语音处理等待超时，结果尚未确认；RK 可能仍在处理或已经播报，请先核对状态，不要重复发送。'

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
    const payload = (await response.json()) as { detail?: unknown; error?: unknown }
    const detail = payload.detail || payload.error
    if (Array.isArray(detail)) return '请求参数无效，请检查坐标和输入。'
    const code = typeof detail === 'string' ? detail : ''
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
  const mapMetaError = ref('')
  let mapMetaPending = false
  const mapUpload = ref<MapUploadStatus>({ state: 'idle', detail: '选择场地的 .nvmp 地图包。' })
  const mapUploadError = ref('')
  const mapPreview = ref<MapPreview | null>(null)
  const mapUploading = computed(() => ['queued', 'uploading'].includes(mapUpload.value.state))
  let mapPollBusy = false
  let lastMapPoll = 0
  const mapImageVersion = ref('')
  const allWaypoints = ref<Waypoint[]>([])
  const allPatrolRoutes = ref<PatrolRoute[]>([])
  const currentMapId = computed(() => mapMeta.value?.map_id ?? '')
  const currentMapLabel = computed(() => ({ field_home: '地图 1', field_home2: '地图 2' } as Record<string, string>)[currentMapId.value] ?? (currentMapId.value || '等待地图'))
  const waypoints = computed(() => allWaypoints.value.filter((w) => w.map_id === currentMapId.value))
  const patrolRoutes = computed(() => allPatrolRoutes.value.filter((r) => r.enabled && r.map_id === currentMapId.value))
  const alerts = ref<AlertEvent[]>([])
  const taskEvents = ref<TaskEvent[]>([])
  const trail = ref<Point[]>([])
  const logs = ref<LogLine[]>([])
  const token = ref(window.localStorage.getItem(TOKEN_KEY) ?? '')
  const pending = ref<PendingCommand | null>(null)
  const smart = ref<SmartCommandResult | null>(null)
  const conn = reactive({ state: false, nav: false })
  const busy = reactive({ mission: false, pause: false, cancel: false, pose: false, voice: false, confirm: false, mode: false, estop: false, map: false })
  const voiceStatus = ref('空闲')
  const voiceError = ref('')
  const confirmError = ref('')
  const lastMessage = ref('等待命令')
  const toast = ref<{ id: number; text: string; tone: Tone } | null>(null)
  let toastTimer = 0

  const platform = computed(() => state.value?.platform_status ?? null)
  const isMock = computed(() => state.value?.system_mode.mode !== 'real')
  const detections = computed(() => state.value?.detection_status?.objects ?? [])
  const taskActive = computed(() => ['pending', 'running', 'paused'].includes(state.value?.task_status.state ?? ''))
  const poseInteractionBusy = computed(() => busy.pose || busy.mode || busy.map || mapUploading.value)
  const navigationBusy = computed(() => busy.mission || busy.pause || busy.cancel || poseInteractionBusy.value || taskActive.value)

  let stateSocket: WebSocket | null = null
  let navSocket: WebSocket | null = null
  let timers: number[] = []
  let running = false
  let lifecycle = 0
  let stateReconnect = 0
  let navReconnect = 0

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
      const response = await fetch(apiUrl(path), { signal: AbortSignal.timeout(5000) })
      return response.ok ? ((await response.json()) as T) : null
    } catch {
      return null
    }
  }

  async function request<T>(path: string, init: RequestInit, fallback: string,
    timeoutMs = 12000, timeoutMessage = '请求超时，请核对当前状态；暂停、取消和急停仍可使用。'): Promise<T> {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(apiUrl(path), {
        ...init, signal: controller.signal,
      })
      if (!response.ok) throw new Error(await readApiError(response, fallback))
      return (await response.json()) as T
    } catch (error) {
      if (controller.signal.aborted) throw new Error(timeoutMessage)
      throw error
    } finally { window.clearTimeout(timeout) }
  }

  async function post<T>(path: string, body: unknown, fallback: string,
    timeoutMs = 12000, timeoutMessage?: string): Promise<T> {
    return request<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(body) }, fallback, timeoutMs, timeoutMessage)
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
    const payload = await getJson<{ data: Waypoint[]; patrol_routes?: PatrolRoute[] }>('/api/waypoints')
    if (payload) {
      allWaypoints.value = payload.data.filter((w) => w.enabled)
      allPatrolRoutes.value = payload.patrol_routes ?? []
    }
  }

  async function loadMapMeta() {
    if (mapMetaPending) return
    mapMetaPending = true
    try {
      const payload = await getJson<{ data: MapMetadata }>('/api/navigation/map/metadata')
      if (!payload?.data) {
        mapMetaError.value = mapMeta.value ? '地图信息暂时不可用，显示上次地图并重试。' : '地图信息暂时不可用，正在重试。'
        return
      }
      mapMeta.value = payload.data
      mapImageVersion.value = payload.data.version
      mapMetaError.value = ''
    } finally { mapMetaPending = false }
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

  async function uploadMap(file: File, mapId = mapMeta.value?.map_id || 'yuntuo_field') {
    if (!file.name.toLowerCase().endsWith('.nvmp') || file.size < 48 || file.size > 86064) {
      log('请选择有效的 .nvmp 文件（48至86064字节）。', 'warn', '地图')
      return
    }
    busy.map = true
    mapUploadError.value = ''
    try {
      const query = new URLSearchParams({ filename: file.name, map_id: mapId })
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

  async function previewMap(file: File, mapId = mapMeta.value?.map_id || 'yuntuo_field'): Promise<boolean> {
    busy.map = true
    mapUploadError.value = ''
    try {
      const query = new URLSearchParams({ filename: file.name, map_id: mapId, preview: 'true' })
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

  function applyNavigation(snapshot: NavigationSnapshot | null) {
    if (!snapshot) { nav.value = null; trail.value = []; return }
    if (nav.value?.map_version && nav.value.map_version !== snapshot.map_version) trail.value = []
    nav.value = snapshot
    pushTrail(snapshot)
    if (snapshot.map_version && snapshot.map_version !== mapImageVersion.value) void loadMapMeta()
  }

  async function loadNavigation() {
    const payload = await getJson<{ data: NavigationSnapshot | null }>('/api/navigation/latest')
    // A slow HTTP fallback must not replace a newer, restored WebSocket stream.
    if (payload && (!conn.nav || !nav.value)) applyNavigation(payload.data)
  }

  // ------------------------------------------------------------ 实时流
  function connectState() {
    if (!running) return
    const socket = new WebSocket(wsUrl('/ws/state'))
    stateSocket = socket
    socket.onopen = () => {
      if (!running || stateSocket !== socket) return
      conn.state = true
      void loadState()
    }
    socket.onmessage = (event) => {
      if (!running || stateSocket !== socket) return
      const payload = JSON.parse(event.data) as { type: string; data: RobotState }
      if (payload.type === 'robot_state') state.value = payload.data
    }
    socket.onclose = () => {
      if (stateSocket !== socket) return
      stateSocket = null
      conn.state = false
      if (running) stateReconnect = window.setTimeout(connectState, 3000)
    }
  }

  function connectNav() {
    if (!running) return
    const socket = new WebSocket(wsUrl('/ws/navigation'))
    navSocket = socket
    socket.onopen = () => {
      if (!running || navSocket !== socket) return
      conn.nav = true
    }
    socket.onmessage = (event) => {
      if (!running || navSocket !== socket) return
      const payload = JSON.parse(event.data) as { type: string; data: NavigationSnapshot | null }
      if (payload.type === 'navigation') applyNavigation(payload.data)
    }
    socket.onclose = () => {
      if (navSocket !== socket) return
      navSocket = null
      conn.nav = false
      if (running) navReconnect = window.setTimeout(connectNav, 3000)
    }
  }

  async function start() {
    if (running) return
    const current = ++lifecycle
    running = true
    await Promise.all([loadState(), loadNavigation(), loadAlerts(), loadWaypoints(), loadMapMeta(), loadTaskEvents(), loadMapUpload()])
    if (!running || current !== lifecycle) return
    connectState()
    connectNav()
    timers = [
      window.setInterval(() => void loadAlerts(), 5000),
      window.setInterval(() => void loadTaskEvents(), 3000),
      window.setInterval(() => void loadState(), 15000),
      window.setInterval(() => void loadWaypoints(), 60000),
      window.setInterval(() => void loadMapMeta(), 5000),
      window.setInterval(() => { if (!conn.nav) void loadNavigation() }, 3000),
      window.setInterval(() => {
        if (!busy.map && Date.now() - lastMapPoll >= (mapUploading.value ? 1000 : 5000)) void loadMapUpload()
      }, 1000),
    ]
  }

  function stop() {
    running = false
    lifecycle++
    window.clearTimeout(stateReconnect)
    window.clearTimeout(navReconnect)
    const previousState = stateSocket, previousNav = navSocket
    stateSocket = navSocket = null
    previousState?.close()
    previousNav?.close()
    conn.state = conn.nav = false
    timers.forEach((t) => window.clearInterval(t))
    timers = []
    window.clearTimeout(toastTimer)
  }

  // ------------------------------------------------------------ 任务
  type MissionResponse = { data: { accepted: boolean; detail: string } }

  async function mission(command: string, body: Record<string, PayloadValue> = {}) {
    const busyKey: 'pause' | 'cancel' | 'mission' = command === 'pause' ? 'pause' : command === 'cancel' ? 'cancel' : 'mission'
    const stopping = busyKey !== 'mission'
    if (stopping ? busy[busyKey] : (busy.mission || busy.pause || busy.cancel || poseInteractionBusy.value)) {
      log('正在处理上一项操作，请稍候。', 'wait', '任务')
      return null
    }
    if (taskActive.value && ['go_to_waypoint', 'go_to_point', 'start_patrol', 'return_home', 'search_target', 'follow_target'].includes(command)) {
      log('已有活动任务，请先取消当前任务。', 'warn', '任务')
      return null
    }
    busy[busyKey] = true
    try {
      const payload = await post<MissionResponse>(`/api/mission/${command}`,
        { source: 'web', requested_by: 'dashboard', ...body }, '任务接口调用失败')
      log(payload.data.detail, payload.data.accepted ? 'ok' : 'warn', '任务')
      await Promise.all([loadState(), loadTaskEvents()])
      return payload
    } catch (error) {
      log(error instanceof Error ? error.message : '任务发送失败', 'bad', '任务')
      return null
    } finally {
      busy[busyKey] = false
    }
  }

  function goTo(waypointId: string) {
    return mission('go_to_waypoint', { waypoint_id: waypointId })
  }

  function goToPoint(x: number, y: number) {
    return mission('go_to_point', { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 })
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

  async function setPose(x: number, y: number, yaw: number) {
    if (poseInteractionBusy.value || busy.mission || busy.pause || busy.cancel) {
      log('上一项请求正在处理；暂停和取消仍可使用，完成后可设置初始位姿。', 'warn', '定位')
      return
    }
    busy.pose = true
    try {
      if (taskActive.value || ['goto', 'search', 'track'].includes(platform.value?.fpga_mode ?? '')) {
        const cancelled = await mission('cancel')
        if (!cancelled?.data.accepted) throw new Error(cancelled?.data.detail || '未能取消当前任务，初始位姿未发送。')
        const deadline = Date.now() + 3000
        do {
          await loadState()
          if (platform.value?.nav_link === 'online' && ['idle', 'estop'].includes(platform.value?.fpga_mode ?? '')) break
          await new Promise((resolve) => window.setTimeout(resolve, 150))
        } while (Date.now() < deadline)
        if (!['idle', 'estop'].includes(platform.value?.fpga_mode ?? '')) throw new Error('已请求取消，导航尚未确认空闲；请稍后重试初始化位姿。')
      }
      const payload = await post<MissionResponse>('/api/platform/set_pose',
        { x, y, yaw, align: true, source: 'web', requested_by: 'dashboard' }, '初始位姿接口调用失败')
      log(payload.data.detail, payload.data.accepted ? 'ok' : 'warn', '定位')
    } catch (error) {
      log(error instanceof Error ? error.message : '初始位姿发送失败', 'bad', '定位')
    } finally {
      busy.pose = false
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

  function beginVoice(status: string) {
    smart.value = null
    voiceError.value = ''
    voiceStatus.value = status
    busy.voice = true
  }

  function failVoice(error: unknown, fallback: string) {
    const message = error instanceof Error ? error.message : fallback
    voiceError.value = message
    voiceStatus.value = message === VOICE_TIMEOUT_MESSAGE ? '结果未确认' : '失败'
    log(message, 'bad', '语音')
  }

  function handleSmart(payload: SmartResponse, fallback: string) {
    // Always show this request's result, including a current ASR failure.
    smart.value = payload.data ?? null
    if (!payload.success || !payload.data) {
      const message = payload.detail || payload.error || payload.data?.error_reason || fallback
      failVoice(new Error(message), fallback)
      return
    }
    const data = payload.data
    smart.value = data
    voiceStatus.value = data.error_reason ? '失败' : '已处理'
    voiceError.value = data.error_reason || ''
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
    if (!text.trim() || busy.voice) return
    beginVoice('理解与回复中')
    try {
      const payload = await post<SmartResponse>('/api/voice/smart_command',
        { text, source: 'dashboard-smart-text', requested_by: 'dashboard', generate_tts: true }, '智能助手调用失败',
        VOICE_TIMEOUT_MS, VOICE_TIMEOUT_MESSAGE)
      handleSmart(payload, '智能助手调用失败')
    } catch (error) {
      failVoice(error, '文本命令发送失败')
    } finally {
      busy.voice = false
    }
  }

  async function recordBrowser(durationS: number) {
    if (busy.voice) return
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      log('当前浏览器不支持网页麦克风录音（需要 HTTPS 或 localhost）', 'warn', '语音')
      return
    }
    beginVoice('录音中')
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
      voiceStatus.value = '识别与回复中'
      const form = new FormData()
      form.append('file', blob, type.includes('ogg') ? 'browser_audio.ogg' : 'browser_audio.webm')
      form.append('source', 'browser-mic')
      form.append('requested_by', 'operator')
      form.append('keep_audio', 'false')
      form.append('smart', 'true')
      const payload = await request<SmartResponse>('/api/voice/browser_smart_command', {
        method: 'POST', headers: { ...authHeaders() }, body: form,
      }, '网页麦克风识别失败（本机直连时请用车载麦克风）', VOICE_TIMEOUT_MS, VOICE_TIMEOUT_MESSAGE)
      handleSmart(payload, '网页麦克风识别失败')
    } catch (error) {
      const message = error instanceof Error ? error.message : '网页麦克风识别失败'
      failVoice(new Error(/denied|Permission/.test(message) ? '浏览器麦克风权限被拒绝' : message), '网页麦克风识别失败')
    } finally {
      stream?.getTracks().forEach((t) => t.stop())
      busy.voice = false
    }
  }

  async function recordOnboard(durationS: number) {
    if (busy.voice) return
    beginVoice('车载录音与回复中')
    try {
      const payload = await post<SmartResponse>('/api/robot/voice/onboard_smart_command',
        { duration: durationS, source: 'web-onboard-mic', requested_by: 'operator', keep_audio: false, smart: true },
        '车载麦克风识别失败', VOICE_TIMEOUT_MS, VOICE_TIMEOUT_MESSAGE)
      handleSmart(payload, '车载麦克风识别失败')
    } catch (error) {
      failVoice(error, '车载麦克风识别失败')
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
    state, nav, mapMeta, mapMetaError, mapPreview, mapImageVersion, mapUpload, mapUploadError, mapUploading, waypoints, patrolRoutes, currentMapId, currentMapLabel, alerts, taskEvents, trail, logs, token, pending, smart, conn, busy,
    voiceStatus, voiceError, confirmError, lastMessage, toast, platform, isMock, detections, timeline, navigationBusy, poseInteractionBusy,
    start, stop, mission, goTo, goToPoint, setPose, searchTarget, followMe, estop, switchMode, saveToken, sendText, recordBrowser,
    recordOnboard, confirm, uploadMap, previewMap, dismissMapPreview, log,
  }
}

export type YunTuo = ReturnType<typeof useYunTuo>
