<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { apiUrl, authHeaders } from '../config/api'

type Point = { x: number; y: number }
type Pose = Point & { yaw: number }
type NavigationSnapshot = {
  frame_id: string
  timestamp: string
  sequence: number
  map_version: string | null
  pose: Pose | null
  goal: Pose | null
  velocity: { vx: number; vy: number; wz: number } | null
  global_path: Point[]
  local_path: Point[]
  nav_state: string
  remaining_distance: number | null
}
type MapMetadata = {
  map_id: string
  version: string
  frame_id: string
  timestamp: string
  resolution: number
  width: number
  height: number
  origin: Pose
  image_url: string
}

const props = defineProps<{
  robotPose?: Pose | null
  goal?: (Partial<Pose> & { id?: string }) | null
  navState?: string | null
  navigation?: NavigationSnapshot | null
  streamConnected?: boolean
}>()

const stage = ref<HTMLDivElement | null>(null)
const mapCanvas = ref<HTMLCanvasElement | null>(null)
const overlayCanvas = ref<HTMLCanvasElement | null>(null)
const metadata = ref<MapMetadata | null>(null)
const mapImage = ref<HTMLImageElement | null>(null)
const mapError = ref('')
const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)
const now = ref(Date.now())
let resizeObserver: ResizeObserver | null = null
let mapRefreshTimer: number | null = null
let ageTimer: number | null = null
let imageObjectUrl = ''
let dragging = false
let pointerX = 0
let pointerY = 0

const activePose = computed<Pose | null>(() => props.navigation?.pose ?? props.robotPose ?? null)
const activeGoal = computed(() => props.navigation?.goal ?? props.goal ?? null)
const globalPath = computed(() => props.navigation?.global_path ?? [])
const localPath = computed(() => props.navigation?.local_path ?? [])
const navStateLabel = computed(() => props.navigation?.nav_state || props.navState || 'waiting')
const streamAge = computed(() => {
  if (!props.navigation?.timestamp) return null
  const stamp = Date.parse(props.navigation.timestamp)
  return Number.isFinite(stamp) ? Math.max(0, (now.value - stamp) / 1000) : null
})
const streamIsFresh = computed(() => Boolean(props.streamConnected && streamAge.value !== null && streamAge.value < 3))
const streamLabel = computed(() => {
  if (!props.streamConnected) return '等待导航流'
  if (!props.navigation) return '已连接，等待位姿'
  if (!streamIsFresh.value) return `数据已过期 ${streamAge.value?.toFixed(1) ?? '--'}s`
  return `实时 ${streamAge.value?.toFixed(1) ?? '0.0'}s`
})
const poseLabel = computed(() => {
  const pose = activePose.value
  return pose ? `${pose.x.toFixed(2)} / ${pose.y.toFixed(2)} / ${pose.yaw.toFixed(2)}` : '-- / -- / --'
})
const headingLabel = computed(() => {
  const pose = activePose.value
  if (!pose) return '--'
  const heading = ((((pose.yaw * 180) / Math.PI) % 360) + 360) % 360
  return `${heading.toFixed(1)} deg`
})
const velocityLabel = computed(() => {
  const velocity = props.navigation?.velocity
  return velocity ? `${velocity.vx.toFixed(2)} / ${velocity.vy.toFixed(2)} m/s` : '--'
})
const remainingLabel = computed(() => {
  const distance = props.navigation?.remaining_distance
  return distance === null || distance === undefined ? '--' : `${distance.toFixed(2)} m`
})
const resolutionLabel = computed(() => metadata.value ? `${metadata.value.resolution.toFixed(2)} m/cell` : '--')

function configureCanvas(canvas: HTMLCanvasElement, width: number, height: number): CanvasRenderingContext2D | null {
  const ratio = window.devicePixelRatio || 1
  const pixelWidth = Math.max(1, Math.round(width * ratio))
  const pixelHeight = Math.max(1, Math.round(height * ratio))
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth
    canvas.height = pixelHeight
  }
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  const context = canvas.getContext('2d')
  if (context) {
    context.setTransform(ratio, 0, 0, ratio, 0, 0)
    context.clearRect(0, 0, width, height)
  }
  return context
}

function viewport() {
  const container = stage.value
  const map = metadata.value
  if (!container || !map) return null
  const width = container.clientWidth
  const height = container.clientHeight
  const padding = Math.min(34, Math.max(16, width * 0.04))
  const fitScale = Math.min((width - padding * 2) / map.width, (height - padding * 2) / map.height)
  const scale = fitScale * zoom.value
  return {
    width,
    height,
    scale,
    offsetX: (width - map.width * scale) / 2 + panX.value,
    offsetY: (height - map.height * scale) / 2 + panY.value,
  }
}

function mapPoint(point: Point): Point | null {
  const map = metadata.value
  const view = viewport()
  if (!map || !view) return null
  const dx = point.x - map.origin.x
  const dy = point.y - map.origin.y
  const cosine = Math.cos(map.origin.yaw)
  const sine = Math.sin(map.origin.yaw)
  const gridX = (cosine * dx + sine * dy) / map.resolution
  const gridY = (-sine * dx + cosine * dy) / map.resolution
  return {
    x: view.offsetX + gridX * view.scale,
    y: view.offsetY + (map.height - gridY) * view.scale,
  }
}

function drawMap() {
  const canvas = mapCanvas.value
  const image = mapImage.value
  const map = metadata.value
  const view = viewport()
  if (!canvas || !stage.value) return
  const context = configureCanvas(canvas, stage.value.clientWidth, stage.value.clientHeight)
  if (!context || !image || !map || !view) return
  context.imageSmoothingEnabled = false
  context.save()
  context.shadowColor = 'rgba(0, 0, 0, 0.32)'
  context.shadowBlur = 18
  context.drawImage(image, view.offsetX, view.offsetY, map.width * view.scale, map.height * view.scale)
  context.restore()
}

function drawPath(
  context: CanvasRenderingContext2D,
  points: Point[],
  color: string,
  width: number,
  dash: number[] = [],
) {
  if (points.length < 2) return
  context.beginPath()
  points.forEach((point, index) => {
    const projected = mapPoint(point)
    if (!projected) return
    if (index === 0) context.moveTo(projected.x, projected.y)
    else context.lineTo(projected.x, projected.y)
  })
  context.strokeStyle = color
  context.lineWidth = width
  context.lineJoin = 'round'
  context.lineCap = 'round'
  context.setLineDash(dash)
  context.stroke()
  context.setLineDash([])
}

function drawOverlay() {
  const canvas = overlayCanvas.value
  if (!canvas || !stage.value) return
  const context = configureCanvas(canvas, stage.value.clientWidth, stage.value.clientHeight)
  if (!context) return

  drawPath(context, globalPath.value, '#f3ad44', 6)
  drawPath(context, localPath.value, '#23b8ba', 2.5, [8, 6])

  const goal = activeGoal.value
  if (goal?.x !== undefined && goal?.y !== undefined) {
    const point = mapPoint({ x: goal.x, y: goal.y })
    if (point) {
      context.beginPath()
      context.arc(point.x, point.y, 8, 0, Math.PI * 2)
      context.fillStyle = '#26c477'
      context.fill()
      context.strokeStyle = 'rgba(38, 196, 119, 0.3)'
      context.lineWidth = 9
      context.stroke()
    }
  }

  const pose = activePose.value
  if (pose) {
    const point = mapPoint(pose)
    if (point) {
      context.save()
      context.translate(point.x, point.y)
      context.rotate(-pose.yaw + (metadata.value?.origin.yaw ?? 0))
      context.beginPath()
      context.moveTo(15, 0)
      context.lineTo(-10, -9)
      context.lineTo(-6, 0)
      context.lineTo(-10, 9)
      context.closePath()
      context.fillStyle = '#fff7e8'
      context.shadowColor = 'rgba(37, 93, 232, 0.8)'
      context.shadowBlur = 14
      context.fill()
      context.strokeStyle = '#255de8'
      context.lineWidth = 3
      context.stroke()
      context.restore()
    }
  }
}

function redraw() {
  drawMap()
  drawOverlay()
}

async function loadMap() {
  try {
    const metadataResponse = await fetch(apiUrl('/api/navigation/map/metadata'), { headers: authHeaders() })
    if (!metadataResponse.ok) throw new Error(`HTTP ${metadataResponse.status}`)
    const payload = await metadataResponse.json() as { data: MapMetadata }
    if (metadata.value?.version === payload.data.version && mapImage.value) return

    const imageResponse = await fetch(apiUrl(payload.data.image_url), { headers: authHeaders() })
    if (!imageResponse.ok) throw new Error(`map image HTTP ${imageResponse.status}`)
    const blob = await imageResponse.blob()
    const objectUrl = URL.createObjectURL(blob)
    const image = new Image()
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () => reject(new Error('map image decode failed'))
      image.src = objectUrl
    })
    if (imageObjectUrl) URL.revokeObjectURL(imageObjectUrl)
    imageObjectUrl = objectUrl
    metadata.value = payload.data
    mapImage.value = image
    mapError.value = ''
    await nextTick()
    redraw()
  } catch {
    mapError.value = '等待 RK3588 导航地图'
  }
}

function resetView() {
  zoom.value = 1
  panX.value = 0
  panY.value = 0
  redraw()
}

function adjustZoom(factor: number) {
  zoom.value = Math.min(4, Math.max(0.6, zoom.value * factor))
  redraw()
}

function handleWheel(event: WheelEvent) {
  event.preventDefault()
  adjustZoom(event.deltaY < 0 ? 1.12 : 0.89)
}

function handlePointerDown(event: PointerEvent) {
  dragging = true
  pointerX = event.clientX
  pointerY = event.clientY
  stage.value?.setPointerCapture(event.pointerId)
}

function handlePointerMove(event: PointerEvent) {
  if (!dragging) return
  panX.value += event.clientX - pointerX
  panY.value += event.clientY - pointerY
  pointerX = event.clientX
  pointerY = event.clientY
  redraw()
}

function handlePointerUp() {
  dragging = false
}

watch(() => props.navigation, drawOverlay, { deep: true })
watch(() => props.navigation?.map_version, () => void loadMap())

onMounted(() => {
  resizeObserver = new ResizeObserver(redraw)
  if (stage.value) resizeObserver.observe(stage.value)
  void loadMap()
  mapRefreshTimer = window.setInterval(() => void loadMap(), 10000)
  ageTimer = window.setInterval(() => { now.value = Date.now() }, 500)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  if (mapRefreshTimer !== null) window.clearInterval(mapRefreshTimer)
  if (ageTimer !== null) window.clearInterval(ageTimer)
  if (imageObjectUrl) URL.revokeObjectURL(imageObjectUrl)
})
</script>

<template>
  <section class="nav-map panel">
    <div class="section-header compact-header">
      <div>
        <p class="section-kicker">Navigation</p>
        <h2>导航实时可视化</h2>
      </div>
      <span class="status-badge" :class="streamIsFresh ? 'tone-success' : 'tone-warning'">{{ streamLabel }}</span>
    </div>

    <div
      ref="stage"
      class="nav-map-stage"
      :class="{ dragging }"
      aria-label="导航地图"
      @wheel="handleWheel"
      @pointerdown="handlePointerDown"
      @pointermove="handlePointerMove"
      @pointerup="handlePointerUp"
      @pointercancel="handlePointerUp"
    >
      <canvas ref="mapCanvas" class="map-layer"></canvas>
      <canvas ref="overlayCanvas" class="map-layer overlay-layer"></canvas>
      <div v-if="mapError" class="map-empty-state">
        <strong>NAVI MAP STANDBY</strong>
        <span>{{ mapError }}</span>
      </div>
      <div class="map-legend" aria-hidden="true">
        <span><i class="legend-robot"></i>车体</span>
        <span><i class="legend-global"></i>全局路径</span>
        <span><i class="legend-local"></i>控制路径</span>
      </div>
      <div class="map-tools">
        <button type="button" title="放大地图" aria-label="放大地图" @click.stop="adjustZoom(1.2)">+</button>
        <button type="button" title="缩小地图" aria-label="缩小地图" @click.stop="adjustZoom(0.83)">−</button>
        <button type="button" title="重置视图" aria-label="重置视图" @click.stop="resetView">◎</button>
      </div>
    </div>

    <div class="nav-map-metrics">
      <div><span>当前位姿 x / y / yaw</span><strong>{{ poseLabel }}</strong></div>
      <div><span>Frame / Map</span><strong>{{ navigation?.frame_id || metadata?.frame_id || 'map' }} / {{ metadata?.map_id || '--' }}</strong></div>
      <div><span>导航状态</span><strong>{{ navStateLabel }}</strong></div>
      <div><span>路径点</span><strong>{{ globalPath.length }} / {{ localPath.length }}</strong></div>
      <div><span>朝向角</span><strong>{{ headingLabel }}</strong></div>
      <div><span>速度 vx / vy</span><strong>{{ velocityLabel }}</strong></div>
      <div><span>剩余路径</span><strong>{{ remainingLabel }}</strong></div>
      <div><span>地图分辨率</span><strong>{{ resolutionLabel }}</strong></div>
    </div>
  </section>
</template>

<style scoped>
.nav-map { min-height: 100%; }
.nav-map-stage {
  position: relative;
  min-height: clamp(330px, 34vw, 520px);
  overflow: hidden;
  touch-action: none;
  cursor: grab;
  border: 1px solid #17140f;
  border-radius: 8px;
  background:
    linear-gradient(rgba(255, 247, 232, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 247, 232, 0.055) 1px, transparent 1px),
    #12110e;
  background-size: 28px 28px;
  box-shadow: inset 0 0 0 1px rgba(255, 247, 232, 0.07);
}
.nav-map-stage.dragging { cursor: grabbing; }
.map-layer { position: absolute; inset: 0; width: 100%; height: 100%; }
.overlay-layer { pointer-events: none; }
.map-empty-state {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  gap: 8px;
  text-align: center;
  color: #817b70;
}
.map-empty-state strong { color: #fff7e8; font-size: 0.82rem; letter-spacing: 0; }
.map-empty-state span { font-size: 0.78rem; }
.map-tools {
  position: absolute;
  top: 12px;
  right: 12px;
  display: grid;
  gap: 5px;
}
.map-tools button {
  width: 34px;
  height: 34px;
  padding: 0;
  border: 1px solid rgba(255, 247, 232, 0.22);
  border-radius: 6px;
  background: rgba(24, 22, 18, 0.88);
  color: #fff7e8;
  font: 700 1.05rem/1 inherit;
  cursor: pointer;
  backdrop-filter: blur(8px);
}
.map-tools button:hover { border-color: #f3ad44; color: #f3ad44; }
.map-legend {
  position: absolute;
  left: 12px;
  bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid rgba(255, 247, 232, 0.14);
  border-radius: 6px;
  background: rgba(24, 22, 18, 0.84);
  color: #b9b1a3;
  font-size: 0.72rem;
  backdrop-filter: blur(8px);
}
.map-legend span { display: inline-flex; align-items: center; gap: 5px; }
.map-legend i { display: inline-block; width: 13px; height: 3px; background: #f3ad44; }
.map-legend .legend-local { background: #23b8ba; }
.map-legend .legend-robot { width: 8px; height: 8px; border-radius: 50%; background: #255de8; }
.nav-map-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.nav-map-metrics > div {
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid var(--border-soft, #ded2bf);
  border-radius: 7px;
  background: rgba(255, 253, 247, 0.72);
}
.nav-map-metrics span { display: block; margin-bottom: 5px; color: #756f65; font-size: 0.72rem; }
.nav-map-metrics strong { display: block; overflow-wrap: anywhere; font-size: 0.86rem; }
@media (max-width: 1100px) {
  .nav-map-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 620px) {
  .nav-map-stage { min-height: 320px; }
  .nav-map-metrics { grid-template-columns: 1fr 1fr; gap: 8px; }
  .map-legend { right: 54px; }
}
</style>
