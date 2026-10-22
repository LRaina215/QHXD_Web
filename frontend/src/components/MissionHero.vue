<script setup lang="ts">
import { computed } from 'vue'
import { Footprints, House, MapPin, Pause, Play, Route, ScanSearch, Square, Bot } from 'lucide-vue-next'
import BrandMark from './BrandMark.vue'
import { PHASE_LABELS, TASK_STATE_LABELS, fmt, taskTone } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const task = computed(() => props.yt.state.value?.task_status ?? null)
const nav = computed(() => props.yt.state.value?.nav_status ?? null)
const active = computed(() => ['pending', 'running', 'paused'].includes(task.value?.state ?? ''))
const idle = computed(() => !task.value || task.value.task_type === 'placeholder')

const icon = computed(() => ({
  go_to_waypoint: MapPin, start_patrol: Route, return_home: House, search_target: ScanSearch, follow_target: Footprints,
} as Record<string, unknown>)[task.value?.task_type ?? ''] ?? Bot)

function pointName(id: string | null | undefined) {
  if (!id) return ''
  return props.yt.waypoints.value.find((w) => w.waypoint_id === id)?.name ?? id
}

const title = computed(() => {
  const t = task.value
  if (!t || idle.value) return '待命'
  const goal = nav.value?.current_goal ?? ''
  const target = goal.startsWith('target:') ? goal.slice(7) : ''
  switch (t.task_type) {
    case 'search_target': return `寻找「${target || '目标'}」`
    case 'follow_target': return `跟随「${target || '人员'}」`
    case 'return_home': return '返回起点'
    case 'start_patrol': return `巡检 · ${pointName(t.current_waypoint_id) || '路线'}`
    default: return `前往 ${pointName(t.current_waypoint_id ?? goal) || '目标点'}`
  }
})
const detail = computed(() => (idle.value ? '选择右侧的视觉任务、定点或巡检，或直接对云拓说话。' : task.value?.detail || props.yt.lastMessage.value))
const progress = computed(() => (idle.value ? 0 : task.value?.progress ?? 0))
const step = computed(() => ((task.value?.waypoint_count ?? 0) > 1 ? `${(task.value!.waypoint_index ?? 0) + 1} / ${task.value!.waypoint_count}` : null))
const remaining = computed(() => nav.value?.remaining_distance ?? props.yt.nav.value?.remaining_distance ?? null)
const busy = computed(() => props.yt.busy.mission)
</script>

<template>
  <section class="hero card" :class="taskTone(task?.state)" aria-live="polite">
    <BrandMark v-if="idle" :size="56" :rounded="16" />
    <div v-else class="icon"><component :is="icon" :size="26" :stroke-width="2" /></div>
    <div class="main">
      <div class="meta">
        <span class="eyebrow">当前任务</span>
        <span class="tag" :class="taskTone(task?.state)"><i class="dot"></i>{{ idle ? '空闲' : TASK_STATE_LABELS[task?.state ?? ''] ?? task?.state }}</span>
        <span v-if="!idle && task?.phase && !['completed', 'failed', 'cancelled'].includes(task.phase)" class="phase">{{ PHASE_LABELS[task.phase] ?? task.phase }}</span>
        <span v-if="step" class="phase num">第 {{ step }} 点</span>
      </div>
      <h2>{{ title }}</h2>
      <p class="detail">{{ detail }}</p>
    </div>
    <div class="prog">
      <div class="pct num">{{ progress }}<small>%</small></div>
      <div class="bar"><i :style="{ width: `${progress}%` }"></i></div>
      <div class="rem num">{{ remaining != null && active ? `剩余 ${fmt(remaining, 2)} m` : '\u00a0' }}</div>
    </div>
    <div class="acts">
      <button v-if="task?.state === 'paused'" type="button" class="btn primary" :disabled="busy" @click="yt.mission('resume')">
        <Play :size="18" />继续
      </button>
      <button v-else type="button" class="btn" :disabled="busy || task?.state !== 'running'" @click="yt.mission('pause')">
        <Pause :size="18" />暂停
      </button>
      <button type="button" class="btn danger-text" :disabled="busy || !active" @click="yt.mission('cancel')">
        <Square :size="16" />取消
      </button>
      <button type="button" class="btn quiet" :disabled="busy || active" @click="yt.mission('return_home')">
        <House :size="18" />返航
      </button>
    </div>
  </section>
</template>

<style scoped>
.hero { display: grid; grid-template-columns: auto minmax(0, 1fr) 220px auto; align-items: center; gap: 22px; padding: 20px 24px; position: relative; overflow: hidden; }
.hero::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--line-2); }
.hero.run::before { background: var(--run); }
.hero.ok::before { background: var(--ok); }
.hero.bad::before { background: var(--bad); }
.hero.wait::before { background: var(--wait); }
.icon { display: grid; place-items: center; width: 56px; height: 56px; border-radius: 16px; background: var(--surface-3); color: var(--ink-2); }
.run .icon { background: var(--run-soft); color: var(--run); }
.ok .icon { background: var(--ok-soft); color: var(--ok); }
.bad .icon { background: var(--bad-soft); color: var(--bad); }
.meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.phase { font-size: 12px; font-weight: 600; color: var(--ink-2); padding: 0 8px; height: 24px; display: inline-flex; align-items: center; border-radius: 999px; background: var(--surface-2); }
h2 { margin: 4px 0 2px; font-size: 26px; line-height: 1.2; font-weight: 720; letter-spacing: -0.02em; }
.detail { margin: 0; color: var(--ink-2); font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prog { display: grid; gap: 8px; }
.pct { font-size: 34px; font-weight: 700; line-height: 1; letter-spacing: -0.03em; }
.pct small { font-size: 16px; font-weight: 600; color: var(--ink-3); margin-left: 2px; }
.bar { height: 6px; border-radius: 999px; background: var(--surface-3); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: inherit; background: var(--ink); transition: width 0.5s cubic-bezier(.2, .8, .2, 1); }
.run .bar i { background: var(--run); }
.ok .bar i { background: var(--ok); }
.rem { font-size: 12px; color: var(--ink-3); font-weight: 550; }
.acts { display: flex; gap: 8px; }
@media (max-width: 1280px) {
  .hero { grid-template-columns: auto minmax(0, 1fr) 160px; }
  .acts { grid-column: 1 / -1; }
  .acts .btn { flex: 1; }
}
@media (max-width: 720px) {
  .hero { grid-template-columns: auto minmax(0, 1fr); gap: 14px; padding: 18px; }
  .prog { grid-column: 1 / -1; grid-template-columns: auto 1fr; align-items: center; column-gap: 14px; }
  .pct { font-size: 26px; grid-row: span 2; }
  .icon { width: 46px; height: 46px; border-radius: 14px; }
  h2 { font-size: 21px; }
  .detail { white-space: normal; }
}
</style>
