<script setup lang="ts">
import { computed } from 'vue'

type RobotPose = {
  x: number
  y: number
  yaw: number
  frame_id?: string
}

type Goal = {
  id?: string
  x?: number
  y?: number
  yaw?: number
}

const props = defineProps<{
  robotPose?: RobotPose | null
  goal?: Goal | null
  globalPath?: Array<{ x: number; y: number }>
  navState?: string | null
}>()

const poseLabel = computed(() => {
  if (!props.robotPose) {
    return '-- / -- / --'
  }
  return `x=${props.robotPose.x.toFixed(2)} / y=${props.robotPose.y.toFixed(2)} / yaw=${props.robotPose.yaw.toFixed(2)}`
})

const frameLabel = computed(() => props.robotPose?.frame_id || 'map')
const goalLabel = computed(() => props.goal?.id || '--')
const pathPointCount = computed(() => props.globalPath?.length ?? 0)
</script>

<template>
  <section class="nav-map panel surface-panel">
    <div class="section-header compact-header">
      <div>
        <p class="section-kicker">Navigation</p>
        <h2>导航实时可视化</h2>
      </div>
      <span class="status-badge tone-warning">预留</span>
    </div>

    <div class="nav-map-canvas" aria-label="导航地图占位区">
      <div class="map-grid"></div>
      <div class="robot-marker">
        <span></span>
      </div>
      <div class="goal-marker"></div>
      <svg class="path-line" viewBox="0 0 100 100" aria-hidden="true">
        <path d="M18 72 C34 52, 45 58, 58 38 S78 24, 86 18" />
      </svg>
      <p>等待接入 NUC 导航实时流</p>
    </div>

    <div class="nav-map-metrics">
      <div>
        <span>当前位姿</span>
        <strong>{{ poseLabel }}</strong>
      </div>
      <div>
        <span>Frame</span>
        <strong>{{ frameLabel }}</strong>
      </div>
      <div>
        <span>当前目标点</span>
        <strong>{{ goalLabel }}</strong>
      </div>
      <div>
        <span>导航状态</span>
        <strong>{{ navState || '--' }}</strong>
      </div>
      <div>
        <span>路径点</span>
        <strong>{{ pathPointCount }}</strong>
      </div>
    </div>
  </section>
</template>

<style scoped>
.nav-map {
  min-height: 100%;
}

.nav-map-canvas {
  position: relative;
  min-height: 330px;
  overflow: hidden;
  border: 1px solid rgba(37, 99, 235, 0.14);
  border-radius: 8px;
  background: linear-gradient(180deg, #f8fbff 0%, #eff6ff 100%);
}

.map-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(37, 99, 235, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(37, 99, 235, 0.08) 1px, transparent 1px);
  background-size: 28px 28px;
}

.path-line {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.path-line path {
  fill: none;
  stroke: #2563eb;
  stroke-width: 2.6;
  stroke-linecap: round;
  stroke-dasharray: 6 7;
}

.robot-marker {
  position: absolute;
  left: 24%;
  bottom: 24%;
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid rgba(37, 99, 235, 0.28);
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.16);
}

.robot-marker span {
  width: 0;
  height: 0;
  border-left: 9px solid transparent;
  border-right: 9px solid transparent;
  border-bottom: 21px solid #2563eb;
  transform: rotate(36deg);
}

.goal-marker {
  position: absolute;
  top: 17%;
  right: 13%;
  width: 18px;
  height: 18px;
  border-radius: 999px;
  background: #16a34a;
  box-shadow: 0 0 0 8px rgba(22, 163, 74, 0.12);
}

.nav-map-canvas p {
  position: absolute;
  left: 20px;
  bottom: 18px;
  margin: 0;
  color: #64748b;
  font-size: 0.92rem;
}

.nav-map-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.nav-map-metrics div {
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
}

.nav-map-metrics span {
  display: block;
  margin-bottom: 6px;
  color: #64748b;
  font-size: 0.82rem;
}

.nav-map-metrics strong {
  color: #0f172a;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
</style>
