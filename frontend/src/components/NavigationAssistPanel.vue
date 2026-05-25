<script setup lang="ts">
import { computed } from 'vue'

type TaskStatus = {
  task_id: string
  task_type: string
  state: string
  progress: number
  source: string
}

type NavStatus = {
  mode: string
  state: string
  current_goal: string | null
  remaining_distance: number | null
}

type RobotPose = {
  x: number
  y: number
  yaw: number
  frame_id: string
  timestamp: string
}

type DeviceStatus = {
  battery_percent: number | null
  emergency_stop: boolean
  fault_code: string | null
  online: boolean
}

type AlertEvent = {
  alert_id: string
  level: string
  message: string
  source: string
  timestamp: string
  acknowledged: boolean
}

const props = defineProps<{
  taskStatus?: TaskStatus | null
  navStatus?: NavStatus | null
  robotPose?: RobotPose | null
  deviceStatus?: DeviceStatus | null
  systemMode?: string | null
  alerts?: AlertEvent[]
  updatedAt?: string | null
  wsConnected?: boolean
  imuWsConnected?: boolean
  connectionLabel?: string
  imuConnectionLabel?: string
  voiceText?: string | null
  llmTarget?: string | null
  confirmationState?: string | null
}>()

const missionLabel = computed(() => {
  if (!props.taskStatus) {
    return 'waiting'
  }
  return `${props.taskStatus.state} / ${props.taskStatus.progress}%`
})

const poseAgeLabel = computed(() => {
  const stamp = props.robotPose?.timestamp || props.updatedAt
  if (!stamp) {
    return '--'
  }
  const time = Date.parse(stamp)
  if (Number.isNaN(time)) {
    return '--'
  }
  return `${Math.max(0, (Date.now() - time) / 1000).toFixed(1)}s`
})

const remainingDistanceLabel = computed(() => {
  const distance = props.navStatus?.remaining_distance
  return distance === null || distance === undefined ? '--' : `${distance.toFixed(2)} m`
})

const latestAlertLabel = computed(() => {
  const alert = props.alerts?.[0]
  if (!alert) {
    return 'normal'
  }
  return `${alert.level} / ${alert.message}`
})

const timelineItems = computed(() => [
  {
    label: '语音识别',
    value: props.voiceText || 'waiting',
    state: props.voiceText ? 'done' : 'wait',
  },
  {
    label: 'LLM 解析',
    value: props.llmTarget || props.navStatus?.current_goal || props.taskStatus?.task_id || 'waiting',
    state: props.llmTarget || props.navStatus?.current_goal || props.taskStatus?.task_id ? 'done' : 'wait',
  },
  {
    label: '用户确认',
    value: props.confirmationState || '--',
    state: props.confirmationState?.includes('待') ? 'pending' : props.confirmationState && props.confirmationState !== '--' ? 'done' : 'wait',
  },
  {
    label: 'Mission',
    value: missionLabel.value,
    state: props.taskStatus?.state && props.taskStatus.state !== 'idle' ? 'active' : 'wait',
  },
])

const linkItems = computed(() => [
  { label: 'NUC state', value: props.deviceStatus?.online ? 'online' : 'offline' },
  { label: 'WS state', value: props.wsConnected ? 'connected' : 'reconnecting' },
  { label: 'IMU stream', value: props.imuWsConnected ? 'connected' : 'waiting' },
  { label: 'mode', value: props.systemMode || '--' },
  { label: 'pose age', value: poseAgeLabel.value },
  { label: 'alert', value: latestAlertLabel.value },
])

const motionItems = computed(() => [
  { label: 'vx', value: '--' },
  { label: 'vy', value: '--' },
  { label: 'wz', value: '--' },
  { label: 'remaining', value: remainingDistanceLabel.value },
  { label: 'goal', value: props.navStatus?.current_goal || props.taskStatus?.task_id || '--' },
  { label: 'nav', value: props.navStatus?.state || '--' },
])
</script>

<template>
  <article class="navigation-assist-panel panel">
    <div class="section-header compact-header">
      <div>
        <p class="section-kicker">Navigation Assist</p>
        <h2>任务执行链路</h2>
      </div>
      <span class="hint-text">后续可平滑接入真实导航流</span>
    </div>

    <div class="assist-layout">
      <section class="timeline-card" aria-label="任务执行时间线">
        <div class="assist-title-row">
          <span>Task timeline</span>
          <strong>{{ props.taskStatus?.task_type || 'waiting' }}</strong>
        </div>
        <ol class="mission-timeline">
          <li v-for="item in timelineItems" :key="item.label" :class="`timeline-${item.state}`">
            <span class="timeline-dot"></span>
            <div>
              <strong>{{ item.label }}</strong>
              <p>{{ item.value }}</p>
            </div>
          </li>
        </ol>
      </section>

      <section class="assist-status-grid" aria-label="导航链路与运动状态">
        <div class="status-cluster">
          <div class="assist-title-row">
            <span>Nav link</span>
            <strong>{{ props.connectionLabel || '--' }}</strong>
          </div>
          <dl>
            <template v-for="item in linkItems" :key="item.label">
              <dt>{{ item.label }}</dt>
              <dd>{{ item.value }}</dd>
            </template>
          </dl>
        </div>

        <div class="status-cluster">
          <div class="assist-title-row">
            <span>Motion reserve</span>
            <strong>{{ props.navStatus?.state || 'waiting' }}</strong>
          </div>
          <dl>
            <template v-for="item in motionItems" :key="item.label">
              <dt>{{ item.label }}</dt>
              <dd>{{ item.value }}</dd>
            </template>
          </dl>
        </div>
      </section>
    </div>
  </article>
</template>

<style scoped>
.navigation-assist-panel {
  container-type: inline-size;
  display: grid;
  gap: 12px;
}

.assist-layout {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: stretch;
  gap: 12px;
}

.timeline-card,
.status-cluster {
  min-width: 0;
  overflow: hidden;
  padding: 13px;
  border: 1px solid #e0d4c4;
  border-radius: 8px;
  background: rgba(255, 253, 248, 0.72);
}

.assist-title-row {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: start;
  gap: 10px;
  margin-bottom: 10px;
}

.assist-title-row span {
  color: #255de8;
  font-family: "DIN Alternate", "Avenir Next", sans-serif;
  font-size: 0.72rem;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  white-space: nowrap;
}

.assist-title-row strong {
  min-width: 0;
  color: #15130f;
  line-height: 1.3;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  overflow-wrap: normal;
  word-break: normal;
}

.mission-timeline {
  list-style: none;
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
}

.mission-timeline li {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: 9px;
  align-items: start;
}

.timeline-dot {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 999px;
  background: #b8aa97;
  box-shadow: 0 0 0 4px rgba(184, 170, 151, 0.15);
}

.timeline-done .timeline-dot {
  background: #20834a;
  box-shadow: 0 0 0 4px rgba(32, 131, 74, 0.14);
}

.timeline-active .timeline-dot {
  background: #255de8;
  box-shadow: 0 0 0 4px rgba(37, 93, 232, 0.14);
}

.timeline-pending .timeline-dot {
  background: #d98218;
  box-shadow: 0 0 0 4px rgba(217, 130, 24, 0.16);
}

.mission-timeline strong {
  color: #15130f;
  font-size: 0.9rem;
}

.mission-timeline p {
  margin: 2px 0 0;
  color: #726a5f;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.assist-status-grid {
  display: contents;
}

dl {
  display: grid;
  grid-template-columns: minmax(86px, auto) minmax(96px, 1fr);
  gap: 8px 10px;
  margin: 0;
}

dt {
  color: #726a5f;
  font-size: 0.8rem;
}

dd {
  min-width: 0;
  margin: 0;
  color: #15130f;
  font-weight: 800;
  text-align: right;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  overflow-wrap: normal;
  word-break: keep-all;
}

@container (max-width: 760px) {
  .assist-layout {
    grid-template-columns: 1fr;
  }

  .assist-status-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
}

@container (max-width: 540px) {
  .assist-status-grid {
    grid-template-columns: 1fr;
  }

  .assist-title-row {
    grid-template-columns: 1fr;
  }

  .assist-title-row strong {
    text-align: left;
  }

  dl {
    grid-template-columns: 1fr;
  }

  dd {
    text-align: left;
    white-space: normal;
  }
}
</style>
