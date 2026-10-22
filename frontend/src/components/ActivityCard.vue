<script setup lang="ts">
import { Activity } from 'lucide-vue-next'
import { clock } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

defineProps<{ yt: YunTuo }>()
</script>

<template>
  <section class="card act">
    <div class="card-head">
      <h2 class="card-title"><Activity :size="17" />动态</h2>
      <span class="spacer"></span>
      <span class="eyebrow num">{{ yt.timeline.value.length }} 条</span>
    </div>
    <ol class="card-body list">
      <li v-for="e in yt.timeline.value" :key="e.id" :class="e.tone">
        <i></i>
        <div>
          <p>{{ e.text }}</p>
          <span class="num">{{ clock(e.time) }} · {{ e.source }}</span>
        </div>
      </li>
      <li v-if="!yt.timeline.value.length" class="empty">暂无动态</li>
    </ol>
  </section>
</template>

<style scoped>
.act { display: flex; flex-direction: column; min-height: 0; }
.list { list-style: none; margin: 0; overflow-y: auto; max-height: 330px; display: grid; gap: 2px; align-content: start; }
.list li { display: grid; grid-template-columns: 14px 1fr; gap: 10px; padding: 8px 0; }
.list li + li { border-top: 1px solid var(--line); }
.list i { width: 8px; height: 8px; margin-top: 7px; border-radius: 50%; background: var(--off); }
.ok i { background: var(--ok); } .run i { background: var(--run); } .warn i { background: var(--warn); }
.bad i { background: var(--bad); } .wait i { background: var(--wait); } .mock i { background: var(--mock); }
.list p { margin: 0; font-size: 13px; line-height: 1.5; }
.bad p { color: var(--bad); }
.list span { font-size: 11px; color: var(--ink-3); }
.list li.empty { display: grid; grid-template-columns: 1fr; border: 1px dashed var(--line-2); }
</style>
