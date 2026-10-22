<script setup lang="ts">
import { computed, ref } from 'vue'
import { CLASS_LABELS, COLOR_LABELS, COLOR_SWATCH, PHASE_LABELS, TASK_STATE_LABELS, TASK_TYPE_LABELS, targetLabel, taskTone } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const selected = defineModel<string>('selected', { required: true })
const targetClass = ref('bottle')
const targetColor = ref<string | null>('red')
const classes = ['bottle', 'cup', 'person', 'sports ball', 'chair', 'backpack']
const colors = ['red', 'green', 'blue', 'yellow', 'white', 'black']

const task = computed(() => props.yt.state.value?.task_status ?? null)
const active = computed(() => ['pending', 'running', 'paused'].includes(task.value?.state ?? ''))
const busy = computed(() => props.yt.busy.mission)
const configured = computed(() => props.yt.waypoints.value.filter((w) => w.configured))

function startSearch() {
  void props.yt.searchTarget(targetClass.value, targetColor.value, targetLabel(targetClass.value, targetColor.value))
}

function toggleColor(color: string) {
  targetColor.value = targetColor.value === color ? null : color
}
</script>

<template>
  <section class="panel task-panel">
    <div class="panel-head">
      <h2 class="panel-title">任务 <small>MISSION</small></h2>
      <span class="pill" :class="`tone-${taskTone(task?.state)}`">{{ TASK_STATE_LABELS[task?.state ?? 'idle'] ?? task?.state }}</span>
    </div>
    <div class="panel-body">
      <div class="current">
        <div class="cur-line">
          <strong>{{ TASK_TYPE_LABELS[task?.task_type ?? 'placeholder'] ?? task?.task_type }}</strong>
          <span v-if="task?.phase" class="phase">{{ PHASE_LABELS[task.phase] ?? task.phase }}</span>
          <span v-if="task?.waypoint_count" class="phase num">{{ (task.waypoint_index ?? 0) + 1 }}/{{ task.waypoint_count }}</span>
          <span class="num pct">{{ task?.progress ?? 0 }}%</span>
        </div>
        <div class="bar"><i :style="{ width: `${task?.progress ?? 0}%` }"></i></div>
        <p class="detail">{{ task?.detail || yt.lastMessage.value }}</p>
      </div>

      <div class="ctl-row">
        <button type="button" class="btn warn" :disabled="busy || task?.state !== 'running'" @click="yt.mission('pause')">暂停</button>
        <button type="button" class="btn" :disabled="busy || task?.state !== 'paused'" @click="yt.mission('resume')">继续</button>
        <button type="button" class="btn danger" :disabled="busy || !active" @click="yt.mission('cancel')">取消</button>
        <button type="button" class="btn" :disabled="busy || active" @click="yt.mission('return_home')">返航</button>
      </div>

      <h3>定点 / 巡检</h3>
      <div class="goto-row">
        <label class="sr-only" for="wp-select">目标点</label>
        <select id="wp-select" v-model="selected" class="field">
          <option v-for="w in configured" :key="w.waypoint_id" :value="w.waypoint_id">{{ w.name }}</option>
        </select>
        <button type="button" class="btn primary" :disabled="busy || active || !selected" @click="yt.goTo(selected)">前往</button>
        <button type="button" class="btn" :disabled="busy || active" @click="yt.mission('start_patrol', { patrol_id: 'default_patrol' })">巡检</button>
      </div>

      <h3>视觉任务</h3>
      <div class="chips" role="group" aria-label="目标类别">
        <button v-for="c in classes" :key="c" type="button" class="chip" :class="{ on: targetClass === c }" @click="targetClass = c">
          {{ CLASS_LABELS[c] }}
        </button>
      </div>
      <div class="chips" role="group" aria-label="目标颜色（可不选）">
        <button v-for="c in colors" :key="c" type="button" class="chip swatch" :class="{ on: targetColor === c }"
          :aria-pressed="targetColor === c" :title="`${COLOR_LABELS[c]}色`" @click="toggleColor(c)">
          <i :style="{ background: COLOR_SWATCH[c] }"></i>{{ COLOR_LABELS[c] }}
        </button>
      </div>
      <div class="target-row">
        <button type="button" class="btn primary grow" :disabled="busy || active" @click="startSearch">
          寻找「{{ targetLabel(targetClass, targetColor) }}」并停在旁边
        </button>
        <button type="button" class="btn" :disabled="busy || active" @click="yt.followMe()">跟随我</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.current { padding: 12px; border-radius: 10px; background: rgba(47, 224, 196, 0.05); border: 1px solid var(--line); }
.cur-line { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.cur-line strong { font-size: 18px; }
.phase { font-size: 12px; color: var(--accent); }
.pct { margin-left: auto; color: var(--text-2); font-size: 13px; }
.detail { margin: 8px 0 0; color: var(--text-2); font-size: 13px; min-height: 18px; }
.ctl-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 12px; }
h3 { margin: 16px 0 8px; font-size: 12px; color: var(--text-3); font-weight: 600; letter-spacing: 0.08em; }
.goto-row, .target-row { display: flex; gap: 8px; }
.goto-row .field { flex: 1; min-width: 0; }
.grow { flex: 1; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: 999px;
  border: 1px solid var(--line-strong); background: transparent; color: var(--text-2); font-size: 12px;
}
.chip.on { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
.swatch i { width: 10px; height: 10px; border-radius: 50%; border: 1px solid rgba(255, 255, 255, 0.3); }
</style>
