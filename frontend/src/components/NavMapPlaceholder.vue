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
const headingDegLabel = computed(() => {
  if (!props.robotPose) {
    return '--'
  }
  const deg = (props.robotPose.yaw * 180) / Math.PI
  const normalized = ((deg % 360) + 360) % 360
  return `${normalized.toFixed(1)} deg`
})
const originDistanceLabel = computed(() => {
  if (!props.robotPose) {
    return '--'
  }
  return `${Math.hypot(props.robotPose.x, props.robotPose.y).toFixed(2)} m`
})
const goalDistanceLabel = computed(() => {
  if (!props.robotPose || props.goal?.x === undefined || props.goal?.y === undefined) {
    return '等待目标坐标'
  }
  return `${Math.hypot(props.goal.x - props.robotPose.x, props.goal.y - props.robotPose.y).toFixed(2)} m`
})
</script>

<template>
  <section class="nav-map panel">
    <div class="section-header compact-header">
      <div>
        <p class="section-kicker">Navigation</p>
        <h2>导航实时可视化</h2>
      </div>
      <span class="status-badge tone-warning">等待 NUC 流</span>
    </div>

    <div class="nav-map-canvas" aria-label="导航地图占位区">
      <div class="map-grid"></div>
      <div class="range-ring ring-a"></div>
      <div class="range-ring ring-b"></div>
      <div class="map-axis x-axis"></div>
      <div class="map-axis y-axis"></div>
      <svg class="path-line" viewBox="0 0 100 100" aria-hidden="true">
        <path d="M11 78 C28 61, 39 65, 53 43 S75 31, 88 16" />
      </svg>
      <div class="robot-marker" aria-hidden="true">
        <span></span>
      </div>
      <div class="goal-marker" aria-hidden="true"></div>
      <div class="map-caption">
        <strong>NUC NAV STREAM RESERVED</strong>
        <span>等待接入导航实时流；当前区域保留给后续 NavMapCanvas，不直连 ROS2 话题。</span>
      </div>
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
      <div>
        <span>朝向角</span>
        <strong>{{ headingDegLabel }}</strong>
      </div>
      <div>
        <span>离原点距离</span>
        <strong>{{ originDistanceLabel }}</strong>
      </div>
      <div>
        <span>目标距离</span>
        <strong>{{ goalDistanceLabel }}</strong>
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
  min-height: clamp(260px, 26vw, 380px);
  overflow: hidden;
  border: 1px solid #15130f;
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(243, 173, 68, 0.12), transparent 32%),
    linear-gradient(180deg, rgba(255, 247, 232, 0.08), transparent 58%),
    #14130f;
  box-shadow: inset 0 0 0 1px rgba(255, 247, 232, 0.08);
}

.map-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 247, 232, 0.075) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 247, 232, 0.075) 1px, transparent 1px);
  background-size: 30px 30px;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.94), rgba(0, 0, 0, 0.4));
}

.range-ring {
  position: absolute;
  border: 1px solid rgba(28, 167, 170, 0.35);
  border-radius: 999px;
}

.ring-a {
  left: 7%;
  bottom: -18%;
  width: 54%;
  aspect-ratio: 1;
}

.ring-b {
  right: -13%;
  top: -28%;
  width: 52%;
  aspect-ratio: 1;
  border-color: rgba(243, 173, 68, 0.32);
}

.map-axis {
  position: absolute;
  background: rgba(255, 247, 232, 0.25);
}

.x-axis {
  left: 7%;
  right: 8%;
  bottom: 25%;
  height: 1px;
}

.y-axis {
  top: 9%;
  bottom: 12%;
  left: 22%;
  width: 1px;
}

.path-line {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.path-line path {
  fill: none;
  stroke: #f3ad44;
  stroke-width: 2.9;
  stroke-linecap: round;
  stroke-dasharray: 7 8;
  filter: drop-shadow(0 0 10px rgba(243, 173, 68, 0.26));
}

.robot-marker {
  position: absolute;
  left: 22%;
  bottom: 20%;
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: #fff7e8;
  border: 1px solid rgba(255, 247, 232, 0.58);
  box-shadow: 0 16px 34px rgba(0, 0, 0, 0.32), 0 0 0 8px rgba(37, 93, 232, 0.16);
}

.robot-marker span {
  width: 0;
  height: 0;
  border-left: 9px solid transparent;
  border-right: 9px solid transparent;
  border-bottom: 23px solid #255de8;
  transform: rotate(36deg);
}

.goal-marker {
  position: absolute;
  top: 15%;
  right: 12%;
  width: 20px;
  height: 20px;
  border-radius: 999px;
  background: #26c26b;
  box-shadow: 0 0 0 9px rgba(38, 194, 107, 0.14), 0 0 22px rgba(38, 194, 107, 0.34);
}

.map-caption {
  position: absolute;
  left: 18px;
  right: 18px;
  bottom: 16px;
  display: grid;
  gap: 4px;
  max-width: 500px;
  padding: 13px 15px;
  border: 1px solid rgba(255, 247, 232, 0.16);
  border-radius: 8px;
  background: rgba(255, 247, 232, 0.09);
  color: #fff7e8;
  backdrop-filter: blur(10px);
}

.map-caption strong {
  font-family: "DIN Alternate", "Avenir Next", sans-serif;
  letter-spacing: 0.08em;
}

.map-caption span {
  color: rgba(255, 247, 232, 0.68);
  font-size: 0.86rem;
  line-height: 1.45;
}

.nav-map-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.nav-map-metrics div {
  min-width: 0;
  padding: 12px;
  border: 1px solid #e0d4c4;
  border-radius: 8px;
  background: rgba(255, 253, 248, 0.72);
}

.nav-map-metrics span {
  display: block;
  margin-bottom: 6px;
  color: #726a5f;
  font-size: 0.82rem;
}

.nav-map-metrics strong {
  color: #15130f;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
</style>
