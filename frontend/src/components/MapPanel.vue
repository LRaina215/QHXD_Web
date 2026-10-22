<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiUrl } from '../config/api'
import { LOC_LABELS, fmt } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'
import type { Point } from '../types'

const props = defineProps<{ yt: YunTuo; selected: string }>()
const emit = defineEmits<{ pick: [waypointId: string] }>()

const wrap = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
let raster: HTMLCanvasElement | null = null
let rasterVersion = ''
let raf = 0
let observer: ResizeObserver | null = null
const DEFAULT_BOUNDS = { x0: -1, y0: -3, x1: 6, y1: 3 }
const ROBOT_L = 0.52
const ROBOT_W = 0.40

const pose = computed(() => props.yt.nav.value?.pose ?? (props.yt.state.value ? {
  x: props.yt.state.value.robot_pose.x, y: props.yt.state.value.robot_pose.y, yaw: props.yt.state.value.robot_pose.yaw,
} : null))
const platform = computed(() => props.yt.platform.value)

async function loadRaster() {
  const meta = props.yt.mapMeta.value
  if (!meta || meta.version === rasterVersion) return
  rasterVersion = meta.version
  try {
    const response = await fetch(apiUrl(`/api/navigation/map/image?v=${encodeURIComponent(meta.version)}`))
    if (!response.ok) throw new Error()
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
      if (g === 205) { d[i + 3] = 0; continue }          // 未知
      const occ = (254 - g) / 254
      d[i] = 20 + occ * 120
      d[i + 1] = 48 + occ * 200
      d[i + 2] = 58 + occ * 197
      d[i + 3] = 90 + occ * 165
    }
    ctx.putImageData(img, 0, 0)
    raster = off
  } catch {
    raster = null
    rasterVersion = ''
  }
}

function worldBounds() {
  const meta = props.yt.mapMeta.value
  const b = meta
    ? { x0: meta.origin.x, y0: meta.origin.y, x1: meta.origin.x + meta.width * meta.resolution, y1: meta.origin.y + meta.height * meta.resolution }
    : { ...DEFAULT_BOUNDS }
  const pts: Point[] = [...props.yt.trail.value]
  if (pose.value) pts.push(pose.value)
  props.yt.waypoints.value.forEach((w) => w.pose && pts.push(w.pose))
  for (const p of pts) {
    b.x0 = Math.min(b.x0, p.x - 0.5); b.x1 = Math.max(b.x1, p.x + 0.5)
    b.y0 = Math.min(b.y0, p.y - 0.5); b.y1 = Math.max(b.y1, p.y + 0.5)
  }
  return b
}

type View = { s: number; ox: number; oy: number; w: number; h: number }

function makeView(w: number, h: number): View {
  const b = worldBounds()
  const pad = 28
  const s = Math.min((w - 2 * pad) / (b.x1 - b.x0), (h - 2 * pad) / (b.y1 - b.y0))
  const ox = (w - s * (b.x1 - b.x0)) / 2 - s * b.x0
  const oy = (h + s * (b.y1 - b.y0)) / 2 + s * b.y0
  return { s, ox, oy, w, h }
}

const toPx = (v: View, p: Point): [number, number] => [v.ox + v.s * p.x, v.oy - v.s * p.y]

function drawGrid(ctx: CanvasRenderingContext2D, v: View) {
  const step = v.s > 90 ? 0.5 : 1
  const x0 = Math.floor(-v.ox / v.s / step) * step
  const x1 = (v.w - v.ox) / v.s
  const y0 = Math.floor((v.oy - v.h) / v.s / step) * step
  const y1 = v.oy / v.s
  ctx.lineWidth = 1
  ctx.font = '10px ui-monospace, monospace'
  ctx.fillStyle = 'rgba(159,177,189,0.45)'
  for (let x = x0; x <= x1; x += step) {
    const [px] = toPx(v, { x, y: 0 })
    ctx.strokeStyle = Math.abs(x) < 1e-6 ? 'rgba(47,224,196,0.35)' : Number.isInteger(x) ? 'rgba(120,180,200,0.12)' : 'rgba(120,180,200,0.05)'
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, v.h); ctx.stroke()
    if (Number.isInteger(x)) ctx.fillText(`${x}`, px + 3, v.h - 6)
  }
  for (let y = y0; y <= y1; y += step) {
    const [, py] = toPx(v, { x: 0, y })
    ctx.strokeStyle = Math.abs(y) < 1e-6 ? 'rgba(47,224,196,0.35)' : Number.isInteger(y) ? 'rgba(120,180,200,0.12)' : 'rgba(120,180,200,0.05)'
    ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(v.w, py); ctx.stroke()
    if (Number.isInteger(y)) ctx.fillText(`${y}`, 4, py - 3)
  }
}

function drawRaster(ctx: CanvasRenderingContext2D, v: View) {
  const meta = props.yt.mapMeta.value
  if (!raster || !meta) return
  const [px, py] = toPx(v, { x: meta.origin.x, y: meta.origin.y + meta.height * meta.resolution })
  ctx.imageSmoothingEnabled = false
  ctx.drawImage(raster, px, py, meta.width * meta.resolution * v.s, meta.height * meta.resolution * v.s)
}

function drawScene(ctx: CanvasRenderingContext2D, v: View, t: number) {
  // 巡检点
  ctx.font = '12px "PingFang SC", "Microsoft YaHei", sans-serif'
  for (const w of props.yt.waypoints.value) {
    if (!w.pose) continue
    const [x, y] = toPx(v, w.pose)
    const sel = w.waypoint_id === props.selected
    ctx.save()
    ctx.translate(x, y); ctx.rotate(Math.PI / 4)
    ctx.fillStyle = sel ? 'rgba(255,181,71,0.95)' : 'rgba(58,168,255,0.85)'
    ctx.fillRect(-5, -5, 10, 10)
    ctx.restore()
    ctx.fillStyle = sel ? '#ffb547' : 'rgba(230,238,243,0.85)'
    ctx.fillText(w.name, x + 10, y - 8)
  }
  // 轨迹
  const trail = props.yt.trail.value
  if (trail.length > 1) {
    ctx.lineWidth = 2
    for (let i = 1; i < trail.length; i++) {
      ctx.strokeStyle = `rgba(47,224,196,${0.08 + 0.6 * (i / trail.length)})`
      const [ax, ay] = toPx(v, trail[i - 1]); const [bx, by] = toPx(v, trail[i])
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke()
    }
  }
  const p = pose.value
  const goal = props.yt.nav.value?.goal
  if (p && goal) {
    const [rx, ry] = toPx(v, p); const [gx, gy] = toPx(v, goal)
    ctx.setLineDash([6, 6]); ctx.strokeStyle = 'rgba(255,181,71,0.7)'; ctx.lineWidth = 1.5
    ctx.beginPath(); ctx.moveTo(rx, ry); ctx.lineTo(gx, gy); ctx.stroke(); ctx.setLineDash([])
    ctx.strokeStyle = '#ffb547'; ctx.lineWidth = 2
    ctx.beginPath(); ctx.arc(gx, gy, 9, 0, Math.PI * 2); ctx.stroke()
    ctx.beginPath(); ctx.arc(gx, gy, 2.5, 0, Math.PI * 2); ctx.fillStyle = '#ffb547'; ctx.fill()
  }
  const target = props.yt.nav.value?.target
  if (target) {
    const [tx, ty] = toPx(v, target)
    const r = 8 + 6 * ((Math.sin(t / 220) + 1) / 2)
    ctx.fillStyle = 'rgba(255,77,94,0.18)'; ctx.beginPath(); ctx.arc(tx, ty, r + 6, 0, Math.PI * 2); ctx.fill()
    ctx.fillStyle = '#ff4d5e'; ctx.beginPath(); ctx.arc(tx, ty, 6, 0, Math.PI * 2); ctx.fill()
    ctx.fillStyle = '#ffd0d5'; ctx.fillText('目标', tx + 10, ty + 4)
  }
  if (p) {
    const [x, y] = toPx(v, p)
    ctx.save()
    ctx.translate(x, y); ctx.rotate(-p.yaw)
    const L = Math.max(ROBOT_L * v.s, 18), W = Math.max(ROBOT_W * v.s, 14)
    ctx.fillStyle = 'rgba(47,224,196,0.22)'; ctx.strokeStyle = '#2fe0c4'; ctx.lineWidth = 2
    ctx.beginPath(); ctx.roundRect(-L / 2, -W / 2, L, W, 5); ctx.fill(); ctx.stroke()
    ctx.fillStyle = '#e6fffb'
    ctx.beginPath(); ctx.moveTo(L / 2 + 8, 0); ctx.lineTo(L / 2 - 4, -6); ctx.lineTo(L / 2 - 4, 6); ctx.closePath(); ctx.fill()
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
  const v = makeView(w, h)
  drawGrid(ctx, v)
  drawRaster(ctx, v)
  drawScene(ctx, v, t)
}

function resize() {
  const c = canvas.value, el = wrap.value
  if (!c || !el) return
  const dpr = window.devicePixelRatio || 1
  c.width = Math.round(el.clientWidth * dpr)
  c.height = Math.round(el.clientHeight * dpr)
}

function onClick(event: MouseEvent) {
  const c = canvas.value
  if (!c) return
  const rect = c.getBoundingClientRect()
  const v = makeView(rect.width, rect.height)
  const hit = props.yt.waypoints.value.find((w) => {
    if (!w.pose) return false
    const [x, y] = toPx(v, w.pose)
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
  <section class="panel map-panel">
    <div class="panel-head">
      <h2 class="panel-title">场地态势 <small>FPGA NAVIGATION</small></h2>
      <div class="head-pills">
        <span class="pill no-dot">{{ yt.mapMeta.value?.version?.startsWith('canvas') || !yt.mapMeta.value ? '无先验图 · 里程计系' : '先验地图' }}</span>
        <span class="pill" :class="platform?.loc_state === 'ok' || platform?.loc_state === 'mapless' ? 'tone-ok' : platform?.loc_state ? 'tone-warn' : 'tone-muted'">
          定位 {{ LOC_LABELS[platform?.loc_state ?? ''] ?? '--' }}<template v-if="platform?.loc_quality != null"> {{ platform.loc_quality }}%</template>
        </span>
      </div>
    </div>
    <div ref="wrap" class="map-wrap">
      <canvas ref="canvas" role="img" aria-label="机器人位置、目标点与轨迹" @click="onClick"></canvas>
      <div class="readout num">
        <div><span>X</span>{{ fmt(pose?.x, 2) }} m</div>
        <div><span>Y</span>{{ fmt(pose?.y, 2) }} m</div>
        <div><span>θ</span>{{ pose ? fmt((pose.yaw * 180) / Math.PI, 0) : '--' }}°</div>
        <div><span>剩余</span>{{ fmt(yt.nav.value?.remaining_distance, 2) }} m</div>
      </div>
      <ul class="legend">
        <li><i class="lg-robot"></i>机器人</li>
        <li><i class="lg-goal"></i>当前目标</li>
        <li><i class="lg-target"></i>视觉目标</li>
        <li><i class="lg-wp"></i>点位（点击选择）</li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.map-panel { display: flex; flex-direction: column; min-height: 420px; }
.head-pills { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.map-wrap {
  position: relative;
  flex: 1;
  min-height: 360px;
  margin: 0 12px 12px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: radial-gradient(circle at 50% 40%, rgba(19, 33, 48, 0.9), rgba(6, 10, 14, 0.95));
  overflow: hidden;
}
canvas { position: absolute; inset: 0; width: 100%; height: 100%; cursor: crosshair; }
.readout {
  position: absolute; top: 10px; left: 10px;
  display: grid; grid-template-columns: repeat(2, auto); gap: 2px 14px;
  padding: 8px 10px; border-radius: 8px; background: rgba(6, 10, 14, 0.72); border: 1px solid var(--line);
  font-size: 12px; color: var(--text);
}
.readout span { color: var(--text-3); margin-right: 6px; }
.legend {
  position: absolute; right: 10px; bottom: 10px; margin: 0; padding: 6px 10px; list-style: none;
  display: flex; gap: 12px; flex-wrap: wrap; font-size: 11px; color: var(--text-2);
  background: rgba(6, 10, 14, 0.72); border: 1px solid var(--line); border-radius: 8px;
}
.legend li { display: flex; align-items: center; gap: 5px; }
.legend i { width: 10px; height: 10px; display: inline-block; }
.lg-robot { background: rgba(47, 224, 196, 0.4); border: 1.5px solid #2fe0c4; border-radius: 3px; }
.lg-goal { border: 2px solid #ffb547; border-radius: 50%; }
.lg-target { background: #ff4d5e; border-radius: 50%; }
.lg-wp { background: #3aa8ff; transform: rotate(45deg) scale(0.8); }
@media (max-width: 640px) { .legend { display: none; } }
</style>
