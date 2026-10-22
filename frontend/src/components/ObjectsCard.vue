<script setup lang="ts">
import { computed } from 'vue'
import { Eye } from 'lucide-vue-next'
import { CLASS_LABELS, COLOR_LABELS, COLOR_SWATCH, clock, fmt } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const det = computed(() => props.yt.state.value?.detection_status ?? null)
const objects = computed(() =>
  [...props.yt.detections.value].sort((a, b) => (a.distance_m ?? 99) - (b.distance_m ?? 99)).slice(0, 6))
// 俯视图：机身在底部中心，x 前 → 屏幕上，y 左 → 屏幕左；量程 4 m，视场 60°
const R = 4
const W = 300, H = 170, OX = 150, OY = 160, S = 150 / R
const wedge = (() => {
  const a = Math.PI / 6
  return `M${OX},${OY} L${OX - Math.sin(a) * R * S},${OY - Math.cos(a) * R * S} A${R * S},${R * S} 0 0 1 ${OX + Math.sin(a) * R * S},${OY - Math.cos(a) * R * S} Z`
})()
function arc(r: number) {
  const a = Math.PI / 6, d = r * S
  return `M${OX - Math.sin(a) * d},${OY - Math.cos(a) * d} A${d},${d} 0 0 1 ${OX + Math.sin(a) * d},${OY - Math.cos(a) * d}`
}
const dots = computed(() => props.yt.detections.value
  .filter((o) => o.position_body_m && o.position_body_m.length >= 2)
  .map((o, i) => ({
    key: `${o.track_id ?? i}`,
    x: OX - o.position_body_m![1] * S,
    y: OY - o.position_body_m![0] * S,
    fill: o.color ? COLOR_SWATCH[o.color] ?? '#8a8f97' : '#8a8f97',
    name: CLASS_LABELS[o.class_name] ?? o.class_name,
  }))
  .filter((d) => d.y > 0 && d.x > 0 && d.x < W))
const goal = computed(() => props.yt.state.value?.nav_status.current_goal ?? '')
const lockedLabel = computed(() => (goal.value.startsWith('target:') && props.yt.nav.value?.target ? goal.value.slice(7) : null))
</script>

<template>
  <section class="card objs">
    <div class="card-head">
      <h2 class="card-title"><Eye :size="17" />视觉目标</h2>
      <span class="spacer"></span>
      <span class="eyebrow num">{{ det ? `${det.model_name ?? '模型'} · ${clock(det.timestamp)}` : '感知未接入' }}</span>
    </div>
    <div class="card-body">
      <ul v-if="objects.length" class="list">
        <li v-for="(o, i) in objects" :key="`${o.track_id ?? 'n'}-${i}`" :class="{ hot: lockedLabel && o.color && lockedLabel.includes(COLOR_LABELS[o.color] ?? '#') }">
          <span class="sw" :style="{ background: o.color ? COLOR_SWATCH[o.color] ?? '#c9c6bd' : '#e4e2db' }"></span>
          <div class="who">
            <strong>{{ o.color ? `${COLOR_LABELS[o.color] ?? ''}色` : '' }}{{ CLASS_LABELS[o.class_name] ?? o.class_name }}</strong>
            <span class="num">#{{ o.track_id ?? '-' }} · 置信度 {{ fmt(o.confidence, 2) }}</span>
          </div>
          <div class="dist num">{{ o.distance_m != null ? fmt(o.distance_m, 2) : '--' }}<small>m</small></div>
        </li>
      </ul>
      <p v-else class="empty">视野内暂无目标</p>
      <figure class="fov">
        <svg :viewBox="`0 0 ${W} ${H}`" role="img" aria-label="相机视野俯视图：目标相对机身的位置">
          <path :d="wedge" fill="rgba(47,91,255,0.07)" stroke="rgba(47,91,255,0.25)" />
          <path v-for="r in [1, 2, 3]" :key="r" :d="arc(r)" fill="none" stroke="rgba(47,91,255,0.28)" stroke-dasharray="2 4" />
          <text v-for="r in [1, 2, 3]" :key="`t${r}`" :x="OX + 4" :y="OY - r * S + 12" class="rt">{{ r }} m</text>
          <g v-for="d in dots" :key="d.key">
            <circle :cx="d.x" :cy="d.y" r="7" :fill="d.fill" stroke="#fff" stroke-width="2" />
            <text :x="d.x + 11" :y="d.y + 4" class="dn">{{ d.name }}</text>
          </g>
          <rect :x="OX - 9" :y="OY - 6" width="18" height="12" rx="3" fill="#15171a" />
          <path :d="`M${OX - 4},${OY - 6} L${OX},${OY - 12} L${OX + 4},${OY - 6} Z`" fill="#2f5bff" />
        </svg>
        <figcaption>相机视野俯视 · 量程 {{ R }} m</figcaption>
      </figure>
    </div>
  </section>
</template>

<style scoped>
.list { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.list li { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 12px; }
.list li:nth-child(odd) { background: var(--surface-2); }
.list li.hot { background: var(--bad-soft); }
.sw { width: 12px; height: 12px; border-radius: 50%; flex: none; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12); }
.who { flex: 1; min-width: 0; display: grid; }
.who strong { font-size: 14px; font-weight: 650; }
.who span { font-size: 12px; color: var(--ink-3); }
.dist { font-size: 20px; font-weight: 700; letter-spacing: -0.02em; }
.dist small { font-size: 12px; color: var(--ink-3); margin-left: 2px; font-weight: 600; }
.objs { display: flex; flex-direction: column; }
.objs .card-body { flex: 1; display: flex; flex-direction: column; }
.fov { margin: auto 0 0; padding-top: 12px; }
.fov svg { display: block; width: 100%; max-height: 190px; }
.fov figcaption { margin-top: 4px; font-size: 11px; color: var(--ink-3); text-align: center; }
.rt { font-size: 10px; fill: #8a8f97; font-weight: 600; }
.dn { font-size: 12px; fill: #15171a; font-weight: 650; }
</style>
