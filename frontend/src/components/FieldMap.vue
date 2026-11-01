<script setup lang="ts">
// 场地态势画布（深色舞台）：先验代价图、场地点位、轨迹、当前目标、视觉目标、机器人与相机视场
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiUrl } from '../config/api'
import { ROBOT_FOOTPRINT } from '../config/robot'
import type { YunTuo } from '../composables/useYunTuo'
import type { Point } from '../types'

const props = defineProps<{ yt: YunTuo; selected?: string; compact?: boolean; poseMode?: boolean }>()
const emit = defineEmits<{ pick: [waypointId: string]; point: [x: number, y: number]; pose: [x: number, y: number, yaw: number] }>()
let drag: { a: Point; b: Point; pointerId: number } | null = null
let panDrag: { pointerId: number; x: number; y: number; ox: number; oy: number; moved: boolean } | null = null
const panX = ref(0), panY = ref(0)
const panning = ref(false)
let suppressClick = false
const map = computed(() => props.yt.mapPreview.value ?? props.yt.mapMeta.value)

const wrap = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
let raster: HTMLCanvasElement | null = null
let rasterVersion = ''
const rasterState = ref<'idle' | 'loading' | 'ready' | 'retrying'>('idle')
let rasterRequest = 0
let rasterAbort: AbortController | null = null
let rasterRetry = 0
let rasterFailures = 0
let disposed = false
let raf = 0
let observer: ResizeObserver | null = null
const FIELD = { x0: -1, y0: -3, x1: 6, y1: 3 }
const CAM_FOV = (60 * Math.PI) / 180
const CAM_RANGE = 3.0
const PILL_FONT = '600 12px "Inter Variable", "PingFang SC", "Microsoft YaHei", sans-serif'
const C = {
  dot: 'rgba(255,255,255,0.10)', axis: 'rgba(255,255,255,0.22)', label: 'rgba(238,241,244,0.42)',
  brand: '#5b7cff', brandSoft: 'rgba(91,124,255,0.18)', robot: '#ffffff', goal: '#ffb020',
  target: '#ff4d5e', wp: 'rgba(238,241,244,0.9)', wpFill: '#171b21',
}

const pose = computed(() => props.yt.nav.value?.pose ?? (props.yt.state.value
  ? { x: props.yt.state.value.robot_pose.x, y: props.yt.state.value.robot_pose.y, yaw: props.yt.state.value.robot_pose.yaw }
  : null))

const rasterSource = computed(() => {
  const meta = map.value
  if (!meta) return null
  const url = props.yt.mapPreview.value?.image_url ?? apiUrl(`/api/navigation/map/image?v=${encodeURIComponent(meta.version)}`)
  return { meta, url, key: JSON.stringify([meta.map_id, meta.version, url]) }
})
const rasterMessage = computed(() => {
  if (!props.yt.mapPreview.value && props.yt.mapMetaError?.value) return props.yt.mapMetaError.value
  if (!map.value) return '地图信息加载中…'
  if (map.value.version.startsWith('canvas')) return '当前为临时坐标画布，等待先验地图。'
  if (rasterState.value === 'retrying') return '地图图片暂时无法加载，正在重试…'
  if (rasterState.value === 'loading') return '地图图片加载中…'
  return ''
})

async function loadRaster() {
  const source = rasterSource.value
  if (disposed || !source) return
  const { meta, url, key } = source
  if (meta.version.startsWith('canvas') || (key === rasterVersion && raster)) return
  const request = ++rasterRequest
  const controller = new AbortController()
  rasterAbort = controller
  const timeout = window.setTimeout(() => controller.abort(), 6000)
  rasterState.value = rasterFailures ? 'retrying' : 'loading'
  try {
    const response = await fetch(url, { signal: controller.signal })
    if (!response.ok) throw new Error('map')
    const etag = response.headers.get('etag')?.replace(/^W\//, '').replace(/^"|"$/g, '')
    if (etag && etag !== meta.version) throw new Error('map version changed')
    const bitmap = await createImageBitmap(await response.blob())
    if (disposed || request !== rasterRequest || rasterSource.value?.key !== key) { bitmap.close(); return }
    if (bitmap.width !== meta.width || bitmap.height !== meta.height) { bitmap.close(); throw new Error('map dimensions changed') }
    const off = document.createElement('canvas')
    off.width = bitmap.width
    off.height = bitmap.height
    const ctx = off.getContext('2d')!
    ctx.drawImage(bitmap, 0, 0)
    bitmap.close()
    const img = ctx.getImageData(0, 0, off.width, off.height)
    const d = img.data
    for (let i = 0; i < d.length; i += 4) {
      const g = d[i]
      if (g === 205) { d[i + 3] = 0; continue }
      const occ = (254 - g) / 254
      d[i] = d[i + 1] = d[i + 2] = 255
      d[i + 3] = 10 + occ * 200
    }
    ctx.putImageData(img, 0, 0)
    raster = off
    rasterVersion = key
    rasterFailures = 0
    rasterState.value = 'ready'
  } catch {
    if (disposed || request !== rasterRequest || rasterSource.value?.key !== key) return
    rasterState.value = 'retrying'
    rasterFailures++
    rasterRetry = window.setTimeout(() => void loadRaster(), Math.min(1000 * 2 ** (rasterFailures - 1), 5000))
  } finally {
    window.clearTimeout(timeout)
    if (rasterAbort === controller) rasterAbort = null
  }
}

type View = { s: number; ox: number; oy: number; w: number; h: number }

function bounds() {
  const meta = map.value
  const b = meta && !meta.version.startsWith('canvas')
    ? { x0: meta.origin.x, y0: meta.origin.y, x1: meta.origin.x + meta.width * meta.resolution, y1: meta.origin.y + meta.height * meta.resolution }
    : { ...FIELD }
  if (props.yt.mapPreview.value) return b
  const pts: Point[] = [...props.yt.trail.value]
  if (pose.value) pts.push(pose.value)
  props.yt.waypoints.value.forEach((w) => w.pose && pts.push(w.pose))
  for (const p of pts) {
    b.x0 = Math.min(b.x0, p.x - 0.6); b.x1 = Math.max(b.x1, p.x + 0.6)
    b.y0 = Math.min(b.y0, p.y - 0.6); b.y1 = Math.max(b.y1, p.y + 0.6)
  }
  return b
}

function view(w: number, h: number): View {
  const b = bounds()
  const pad = props.compact ? 14 : 40
  const s = Math.min((w - 2 * pad) / (b.x1 - b.x0), (h - 2 * pad) / (b.y1 - b.y0))
  return { s, ox: (w - s * (b.x1 - b.x0)) / 2 - s * b.x0 + panX.value, oy: (h + s * (b.y1 - b.y0)) / 2 + s * b.y0 + panY.value, w, h }
}

const px = (v: View, p: Point): [number, number] => [v.ox + v.s * p.x, v.oy - v.s * p.y]

function pill(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, fg: string, bg: string) {
  ctx.font = PILL_FONT
  const w = ctx.measureText(text).width + 14
  ctx.fillStyle = bg
  ctx.beginPath(); ctx.roundRect(x, y - 11, w, 22, 11); ctx.fill()
  ctx.fillStyle = fg
  ctx.fillText(text, x + 7, y + 4)
}

function drawBase(ctx: CanvasRenderingContext2D, v: View) {
  const [fx0, fy1] = px(v, { x: FIELD.x0, y: FIELD.y1 })
  const [fx1, fy0] = px(v, { x: FIELD.x1, y: FIELD.y0 })
  if (!raster) {
    ctx.fillStyle = 'rgba(255,255,255,0.025)'
    ctx.beginPath(); ctx.roundRect(fx0, fy1, fx1 - fx0, fy0 - fy1, 14); ctx.fill()
  }
  const step = v.s > 70 ? 0.5 : 1
  ctx.fillStyle = C.dot
  for (let x = Math.ceil(-v.ox / v.s / step) * step; x <= (v.w - v.ox) / v.s; x += step) {
    for (let y = Math.ceil((v.oy - v.h) / v.s / step) * step; y <= v.oy / v.s; y += step) {
      const [a, b] = px(v, { x, y })
      ctx.fillRect(a - 1, b - 1, 2, 2)
    }
  }
  const [zx, zy] = px(v, { x: 0, y: 0 })
  ctx.strokeStyle = C.axis; ctx.lineWidth = 1.5
  ctx.beginPath(); ctx.moveTo(zx, zy); ctx.lineTo(zx + 0.5 * v.s, zy); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(zx, zy); ctx.lineTo(zx, zy - 0.5 * v.s); ctx.stroke()
  if (!props.compact) {
    ctx.font = '600 11px "Inter Variable", sans-serif'; ctx.fillStyle = C.label
    ctx.fillText('x', zx + 0.5 * v.s + 4, zy + 4); ctx.fillText('y', zx - 3, zy - 0.5 * v.s - 6)
  }
  const meta = map.value
  if (raster && meta) {
    const [rx, ry] = px(v, { x: meta.origin.x, y: meta.origin.y + meta.height * meta.resolution })
    ctx.imageSmoothingEnabled = false
    ctx.drawImage(raster, rx, ry, meta.width * meta.resolution * v.s, meta.height * meta.resolution * v.s)
  }
}

function drawScale(ctx: CanvasRenderingContext2D, v: View) {
  if (props.compact) return
  const x = 20, y = 28
  ctx.strokeStyle = C.label; ctx.lineWidth = 2
  ctx.beginPath(); ctx.moveTo(x, y - 4); ctx.lineTo(x, y); ctx.lineTo(x + v.s, y); ctx.lineTo(x + v.s, y - 4); ctx.stroke()
  ctx.font = '600 11px "Inter Variable", sans-serif'; ctx.fillStyle = C.label
  ctx.fillText('1 m', x + v.s + 8, y + 1)
}

function drawScene(ctx: CanvasRenderingContext2D, v: View, t: number) {
  if (props.yt.mapPreview.value) return  // Preview never invents a robot pose or usable task points.
  const trail = props.yt.trail.value
  if (trail.length > 1) {
    ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.lineWidth = props.compact ? 2 : 3
    for (let i = 1; i < trail.length; i++) {
      ctx.strokeStyle = `rgba(91,124,255,${0.05 + 0.75 * (i / trail.length) ** 1.5})`
      const [ax, ay] = px(v, trail[i - 1]); const [bx, by] = px(v, trail[i])
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke()
    }
  }
  for (const w of props.yt.waypoints.value) {
    if (!w.pose) continue
    const [x, y] = px(v, w.pose)
    const sel = w.waypoint_id === props.selected
    ctx.fillStyle = sel ? C.brand : C.wpFill
    ctx.strokeStyle = sel ? C.brand : C.wp; ctx.lineWidth = 2
    ctx.beginPath(); ctx.arc(x, y, sel ? 7 : 5.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
    if (!props.compact) pill(ctx, x + 12, y, w.name, sel ? '#fff' : '#d7dce2', sel ? 'rgba(47,91,255,0.9)' : 'rgba(255,255,255,0.08)')
  }
  if (drag) {
    const [ax, ay] = px(v, drag.a); const [bx, by] = px(v, drag.b)
    ctx.strokeStyle = '#34d399'; ctx.lineWidth = 3; ctx.lineCap = 'round'
    ctx.beginPath(); ctx.arc(ax, ay, 8, 0, Math.PI * 2); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke()
  }
  const p = pose.value
  const goal = props.yt.nav.value?.goal
  if (p && goal) {
    const [rx, ry] = px(v, p); const [gx, gy] = px(v, goal)
    ctx.setLineDash([2, 6]); ctx.strokeStyle = 'rgba(255,176,32,0.8)'; ctx.lineWidth = 2; ctx.lineCap = 'round'
    ctx.beginPath(); ctx.moveTo(rx, ry); ctx.lineTo(gx, gy); ctx.stroke(); ctx.setLineDash([])
    ctx.strokeStyle = C.goal; ctx.lineWidth = 2.5
    ctx.beginPath(); ctx.arc(gx, gy, 9, 0, Math.PI * 2); ctx.stroke()
    ctx.fillStyle = C.goal; ctx.beginPath(); ctx.arc(gx, gy, 3, 0, Math.PI * 2); ctx.fill()
  }
  const target = props.yt.nav.value?.target
  if (target) {
    const [tx, ty] = px(v, target)
    const k = (t % 1600) / 1600
    ctx.strokeStyle = `rgba(255,77,94,${0.6 * (1 - k)})`; ctx.lineWidth = 2
    ctx.beginPath(); ctx.arc(tx, ty, 8 + 18 * k, 0, Math.PI * 2); ctx.stroke()
    ctx.fillStyle = C.target; ctx.beginPath(); ctx.arc(tx, ty, 6, 0, Math.PI * 2); ctx.fill()
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(tx, ty, 6, 0, Math.PI * 2); ctx.stroke()
    if (!props.compact) pill(ctx, tx + 14, ty, '视觉目标', '#fff', 'rgba(229,38,59,0.92)')
  }
  if (p) {
    const [x, y] = px(v, p)
    ctx.save(); ctx.translate(x, y); ctx.rotate(-p.yaw)
    if (!props.compact) {
      const r = CAM_RANGE * v.s
      const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, r)
      grad.addColorStop(0, 'rgba(91,124,255,0.28)'); grad.addColorStop(1, 'rgba(91,124,255,0)')
      ctx.fillStyle = grad
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.arc(0, 0, r, -CAM_FOV / 2, CAM_FOV / 2); ctx.closePath(); ctx.fill()
    }
    const L = ROBOT_FOOTPRINT.lengthM * v.s, W = ROBOT_FOOTPRINT.widthM * v.s
    ctx.shadowColor = 'rgba(91,124,255,0.8)'; ctx.shadowBlur = 6
    ctx.fillStyle = C.robot
    ctx.beginPath(); ctx.roundRect(-L / 2, -W / 2, L, W, Math.min(L, W) / 5); ctx.fill()
    ctx.shadowBlur = 0
    ctx.fillStyle = C.brand
    ctx.beginPath(); ctx.moveTo(L * 0.4, 0); ctx.lineTo(-L * 0.3, -W * 0.3); ctx.lineTo(-L * 0.3, W * 0.3); ctx.closePath(); ctx.fill()
    ctx.restore()
  }
}

function draw(t: number) {
  raf = window.requestAnimationFrame(draw)
  const c = canvas.value
  if (!c || !c.width) return
  const dpr = window.devicePixelRatio || 1
  const ctx = c.getContext('2d')!
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  const w = c.width / dpr, h = c.height / dpr
  ctx.clearRect(0, 0, w, h)
  const v = view(w, h)
  drawBase(ctx, v)
  drawScene(ctx, v, t)
  drawScale(ctx, v)
}

function resize() {
  const c = canvas.value, el = wrap.value
  if (!c || !el) return
  const dpr = window.devicePixelRatio || 1
  c.width = Math.max(1, Math.round(el.clientWidth * dpr))
  c.height = Math.max(1, Math.round(el.clientHeight * dpr))
}

function worldAt(event: PointerEvent | MouseEvent): Point {
  const rect = canvas.value!.getBoundingClientRect()
  const v = view(rect.width, rect.height)
  return { x: (event.clientX - rect.left - v.ox) / v.s, y: (v.oy - (event.clientY - rect.top)) / v.s }
}

function onDown(event: PointerEvent) {
  if (!event.isPrimary || event.button !== 0) return
  suppressClick = false
  if (props.compact || !canvas.value) return
  if (props.poseMode && !props.yt.mapPreview.value) {
    const a = worldAt(event)
    drag = { a, b: a, pointerId: event.pointerId }
  } else {
    panDrag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, ox: panX.value, oy: panY.value, moved: false }
  }
  canvas.value.setPointerCapture(event.pointerId)
}

function onMove(event: PointerEvent) {
  if (drag?.pointerId === event.pointerId) drag.b = worldAt(event)
  if (panDrag?.pointerId === event.pointerId) {
    const dx = event.clientX - panDrag.x, dy = event.clientY - panDrag.y
    if (!panDrag.moved && Math.hypot(dx, dy) < 6) return
    panDrag.moved = true
    panning.value = true
    panX.value = panDrag.ox + dx
    panY.value = panDrag.oy + dy
  }
}

function onUp(event: PointerEvent) {
  if (panDrag?.pointerId === event.pointerId) {
    const moved = panDrag.moved
    panDrag = null
    panning.value = false
    if (moved) suppressClick = true
    else if (event.pointerType === 'touch') {
      // Touch browsers do not consistently synthesize click after a captured drag.
      // Handle taps here and consume any subsequent compatibility click once.
      suppressClick = true
      pickAt(event)
    }
    return
  }
  if (!drag || drag.pointerId !== event.pointerId) return
  const { a } = drag, b = worldAt(event)
  drag = null
  // The parent exits pose mode synchronously; the browser's following click
  // still belongs to this pose gesture and must not become a navigation goal.
  suppressClick = true
  if (!props.poseMode || props.yt.mapPreview.value || props.compact) return
  const yaw = Math.hypot(b.x - a.x, b.y - a.y) > 0.05 ? Math.atan2(b.y - a.y, b.x - a.x) : 0
  emit('pose', a.x, a.y, yaw)
}

function onCancel(event: PointerEvent) {
  if (panDrag?.pointerId === event.pointerId) {
    panDrag = null
    panning.value = false
    suppressClick = true
  }
  if (drag?.pointerId !== event.pointerId) return
  drag = null
  suppressClick = true
}

function resetView() {
  panX.value = panY.value = 0
  panDrag = null
  panning.value = false
}

function onClick(event: MouseEvent) {
  if (suppressClick) {
    suppressClick = false
    event.preventDefault()
    event.stopPropagation()
    return
  }
  pickAt(event)
}

function pickAt(event: MouseEvent) {
  if (props.yt.mapPreview.value || props.poseMode) return
  const c = canvas.value
  if (!c || props.compact) return
  const rect = c.getBoundingClientRect()
  const v = view(rect.width, rect.height)
  const pointerX = event.clientX - rect.left, pointerY = event.clientY - rect.top
  const ctx = c.getContext('2d')!
  ctx.font = PILL_FONT
  const hit = props.yt.waypoints.value.find((w) => {
    if (!w.pose) return false
    const [x, y] = px(v, w.pose)
    return Math.hypot(x - pointerX, y - pointerY) < 16
  }) ?? [...props.yt.waypoints.value].reverse().find((w) => {
    if (!w.pose) return false
    const [x, y] = px(v, w.pose)
    return pointerX >= x + 12 && pointerX <= x + 26 + ctx.measureText(w.name).width && Math.abs(pointerY - y) <= 11
  })
  if (hit) { emit('pick', hit.waypoint_id); return }
  emit('point', (event.clientX - rect.left - v.ox) / v.s, (v.oy - (event.clientY - rect.top)) / v.s)
}

watch(() => rasterSource.value?.key, () => {
  rasterRequest++
  rasterAbort?.abort()
  window.clearTimeout(rasterRetry)
  raster = null
  rasterVersion = ''
  rasterFailures = 0
  rasterState.value = 'idle'
  if (drag || panDrag) suppressClick = true
  drag = null
  resetView()
  void loadRaster()
}, { immediate: true })
onMounted(() => {
  observer = new ResizeObserver(resize)
  if (wrap.value) observer.observe(wrap.value)
  resize()
  raf = window.requestAnimationFrame(draw)
})
onBeforeUnmount(() => {
  disposed = true
  rasterRequest++
  rasterAbort?.abort()
  window.clearTimeout(rasterRetry)
  observer?.disconnect()
  window.cancelAnimationFrame(raf)
})
</script>

<template>
  <div ref="wrap" class="field-map">
    <canvas ref="canvas" role="img" :aria-label="yt.mapPreview.value ? '地图预览，未下发FPGA' : '场地态势：可拖动查看地图，轻点选择目标'" @click="onClick" @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onCancel" @lostpointercapture="onCancel" :class="{ posing: poseMode, panning }"></canvas>
    <button v-if="!compact && (panX || panY)" type="button" class="map-reset" @click.stop="resetView">还原视野</button>
    <div v-if="rasterMessage && !compact" class="map-status" role="status">{{ rasterMessage }}</div>
    <div v-if="yt.mapPreview.value && !compact" class="preview-label">
      <strong>预览 · 未下发FPGA</strong><span>{{ yt.mapPreview.value.filename }}</span>
      <button type="button" @click="yt.dismissMapPreview()">返回机器人地图</button>
    </div>
  </div>
</template>

<style scoped>
.field-map { position: relative; width: 100%; height: 100%; }
.field-map canvas { cursor: grab; touch-action: none; }
.field-map canvas.panning { cursor: grabbing; }
.field-map canvas.posing { cursor: crosshair; touch-action: none; }
.map-reset { position: absolute; top: 48px; left: 16px; padding: 7px 11px; border: 1px solid var(--stage-line); border-radius: 8px; background: rgba(15,18,22,.88); color: var(--stage-ink); font-size: 12px; cursor: pointer; }
.map-status { position: absolute; bottom: 92px; left: 16px; max-width: min(360px, calc(100% - 32px)); padding: 8px 12px; border-radius: 8px; background: rgba(15,18,22,.88); color: var(--stage-ink-2); font-size: 12px; pointer-events: none; }
canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
.preview-label { position: absolute; top: 14px; right: 14px; display: flex; flex-direction: column; align-items: flex-end; gap: 4px; max-width: 62%; padding: 9px 12px; border-radius: 10px; background: rgba(15,18,22,.88); color: #fbbf24; font-size: 12px; }
.preview-label span { color: var(--stage-ink-2); overflow-wrap: anywhere; } .preview-label button { padding: 3px 0; border: 0; background: none; color: #b9c8ff; font-size: 12px; }
</style>
