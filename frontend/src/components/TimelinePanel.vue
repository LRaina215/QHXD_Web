<script setup lang="ts">
import { clock } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

defineProps<{ yt: YunTuo }>()
</script>

<template>
  <section class="panel timeline">
    <div class="panel-head">
      <h2 class="panel-title">事件 <small>EVENTS</small></h2>
      <span class="pill no-dot num">{{ yt.timeline.value.length }}</span>
    </div>
    <ol class="panel-body list" aria-live="polite">
      <li v-for="e in yt.timeline.value" :key="e.id" :class="`t-${e.tone}`">
        <time class="num">{{ clock(e.time) }}</time>
        <span class="src">{{ e.source }}</span>
        <span class="txt">{{ e.text }}</span>
      </li>
      <li v-if="!yt.timeline.value.length" class="empty">暂无事件</li>
    </ol>
  </section>
</template>

<style scoped>
.timeline { display: flex; flex-direction: column; min-height: 0; }
.list { list-style: none; margin: 0; overflow-y: auto; max-height: 340px; }
li { display: grid; grid-template-columns: 64px 52px 1fr; gap: 8px; padding: 6px 0 6px 10px; border-left: 2px solid var(--line); font-size: 12px; position: relative; }
li::before { content: ""; position: absolute; left: -5px; top: 11px; width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
time { color: var(--text-3); }
.src { color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.txt { color: var(--text); line-height: 1.45; }
.t-ok { color: var(--ok); border-left-color: rgba(61, 220, 132, 0.4); }
.t-info { color: var(--info); }
.t-warn { color: var(--warn); border-left-color: rgba(255, 181, 71, 0.4); }
.t-danger { color: var(--danger); border-left-color: rgba(255, 77, 94, 0.5); }
.t-muted { color: var(--muted); }
li.empty { border: 0; display: block; }
li.empty::before { display: none; }
</style>
