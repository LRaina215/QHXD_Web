<script setup lang="ts">
// 场地态势画布（深色舞台）：先验代价图、场地点位、轨迹、当前目标、视觉目标、机器人与相机视场
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiUrl } from '../config/api'
import type { YunTuo } from '../composables/useYunTuo'
import type { Point } from '../types'

const props = defineProps<{ yt: YunTuo; selected?: string; compact?: boolean }>()
const emit = defineEmits<{ pick: [waypointId: string] }>()

const wrap = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
let raster: HTMLCanvasElement | null = null
let rasterVersion = ''
let raf = 0
let observer: ResizeObserver | null = null
const FIELD = { x0: -1, y0: -3, x1: 6, y1: 3 }
const CAM_FOV = (60 * Math.PI) / 180
const CAM_RANGE = 3.0
const C = {
  dot: 'rgba(255,255,255,0.10)', axis: 'rgba(255,255,255,0.22)', label: 'rgba(238,241,244,0.42)',
  brand: '#5b7cff', brandSoft: 'rgba(91,124,255,0.18)', robot: '#ffffff', goal: '#ffb020',
  target: '#ff4d5e', wp: 'rgba(238,241,244,0.9)', wpFill: '#171b21',
}

const pose = computed(() => props.yt.nav.value?.pose ?? (props.yt.state.value
  ? { x: props.yt.state.value.robot_pose.x, y: props.yt.state.value.robot_pose.y, yaw: props.yt.state.value.robot_pose.yaw }
  : null))

async function loadRaster() {
  const meta = props.yt.mapMeta.value
  if (!meta || meta.version === rasterVersion) return
  rasterVersion = meta.version
  if (meta.version.startsWith('canvas')) { raster = null; return }
  try {
    const response = await fetch(apiUrl(`/api/navigation/map/image?v=${encodeURIComponent(meta.version)}`))
    if (!response.ok) throw new Error('map')
    const bitmap = await createImageBitmap(await response.blob())
    const off = document.createElement('canvas')
    off.width = bitmap.width
    off.height = bitmap.height
    const ctx = off.getContext('2d')!
    ctx.drawImage(bitmap, 0, 0)
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
  } catch {
    raster = null
    rasterVersion = ''
  }
}

type View = { s: number; ox: number; oy: number; w: number; h: number }

function bounds() {
  const meta = props.yt.mapMeta.value
  const b = meta && !meta.version.startsWith('canvas')
    ? { x0: meta.origin.x, y0: meta.origin.y, x1: meta.origin.x + meta.width * meta.resolution, y1: meta.origin.y + meta.height * meta.resolution }
    : { ...FIELD }
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
  return { s, ox: (w - s * (b.x1 - b.x0)) / 2 - s * b.x0, oy: (h + s * (b.y1 - b.y0)) / 2 + s * b.y0, w, h }
}

const px = (v: View, p: Point): [number, number] => [v.ox + v.s * p.x, v.oy - v.s * p.y]

function pill(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, fg: string, bg: string) {
  ctx.font = '600 12px "Inter Variable", "PingFang SC", "Microsoft YaHei", sans-serif'
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
  const meta = props.yt.mapMeta.value
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
    const L = Math.max(0.52 * v.s, 18), W = Math.max(0.4 * v.s, 14)
    ctx.shadowColor = 'rgba(91,124,255,0.8)'; ctx.shadowBlur = 16
    ctx.fillStyle = C.robot
    ctx.beginPath(); ctx.roundRect(-L / 2, -W / 2, L, W, Math.min(8, W / 3)); ctx.fill()
    ctx.shadowBlur = 0
    ctx.fillStyle = C.brand
    ctx.beginPath(); ctx.moveTo(L / 2 - 2, 0); ctx.lineTo(L / 2 - W * 0.55, -W * 0.3); ctx.lineTo(L / 2 - W * 0.55, W * 0.3); ctx.closePath(); ctx.fill()
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

function onClick(event: MouseEvent) {
  const c = canvas.value
  if (!c || props.compact) return
  const rect = c.getBoundingClientRect()
  const v = view(rect.width, rect.height)
  const hit = props.yt.waypoints.value.find((w) => {
    if (!w.pose) return false
    const [x, y] = px(v, w.pose)
    return Math.hypot(x - (event.clientX - rect.left), y - (event.clientY - rect.top)) < 16
  })
  if (hit) emit('pick', hit.waypoint_id)
}

watch(() => props.yt.mapMeta.value?.version, () => void loadRaster(), { immediate: true })
onMounted(() => {
  observer = new ResizeObserver(resize)
  if (wrap.value) observer.observe(wrap.value)
  resize()
  raf = window.requestAnimationFrame(draw)
})
onBeforeUnmount(() => { observer?.disconnect(); window.cancelAnimationFrame(raf) })
</script>

<template>
  <div ref="wrap" class="field-map">
    <canvas ref="canvas" role="img" aria-label="场地态势：机器人、点位、轨迹与目标" @click="onClick"></canvas>
  </div>
</template>

<style scoped>
.field-map { position: relative; width: 100%; height: 100%; }
canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
</style>
