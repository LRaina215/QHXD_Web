<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

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
    battery_percent: number
    emergency_stop: boolean
    fault_code: string | null
    online: boolean
  }
  env_sensor: {
    temperature_c: number
    humidity_percent: number
    status: string
  }
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

const state = ref<RobotState | null>(null)
const alerts = ref<AlertEvent[]>([])
const waypointId = ref('mock-waypoint')
const connectionLabel = ref('连接中')
const actionMessage = ref('等待命令')
const isSending = ref(false)
const wsConnected = ref(false)
const shouldReconnect = ref(true)

let socket: WebSocket | null = null
let alertsTimer: number | null = null

const onlineStatus = computed(() => {
  if (!state.value) {
    return '未连接'
  }

  return wsConnected.value && state.value.device_status.online ? '在线' : '离线'
})

const currentTaskLabel = computed(() => {
  if (!state.value) {
    return '暂无任务'
  }

  return `${state.value.task_status.task_type} / ${state.value.task_status.state}`
})

const currentGoalLabel = computed(() => state.value?.nav_status.current_goal ?? '未设置')

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

onMounted(async () => {
  await Promise.all([loadState(), loadAlerts()])
  connectWebSocket()
  alertsTimer = window.setInterval(() => {
    void loadAlerts()
  }, 5000)
})

onBeforeUnmount(() => {
  shouldReconnect.value = false

  if (socket) {
    socket.close()
  }

  if (alertsTimer !== null) {
    window.clearInterval(alertsTimer)
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

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${protocol}://${window.location.host}/ws/state`)

  socket.onopen = () => {
    wsConnected.value = true
    connectionLabel.value = '实时流已连接'
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

function formatNumber(value: number | null | undefined, suffix = '') {
  if (value === null || value === undefined) {
    return '--'
  }

  return `${value}${suffix}`
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString('zh-CN', { hour12: false })
}
</script>

<template>
  <main class="dashboard">
    <section class="panel hero-panel">
      <div>
        <p class="eyebrow">Phase 1 Dashboard</p>
        <h1>RK3588 状态中台</h1>
        <p class="description">
          面向第一阶段联调用的最小看板，使用 mock backend 数据展示状态、告警和任务入口。
        </p>
      </div>
      <div class="stream-status">
        <span class="status-dot" :class="{ live: wsConnected }"></span>
        <strong>{{ connectionLabel }}</strong>
        <small>最近更新时间 {{ lastUpdatedLabel }}</small>
      </div>
    </section>

    <section class="status-grid">
      <article class="card">
        <span class="card-label">在线状态</span>
        <strong>{{ onlineStatus }}</strong>
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
