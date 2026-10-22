<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import CloudVideoPlayer from './CloudVideoPlayer.vue'
import { perceptionFrameStreamUrl } from '../config/api'
import { CLASS_LABELS, COLOR_LABELS, COLOR_SWATCH, clock, fmt } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const frameUrl = ref(perceptionFrameStreamUrl())
let refresher = 0

onMounted(() => {
  // MJPEG 断流后浏览器不会自动重连：定期刷新地址
  refresher = window.setInterval(() => { frameUrl.value = perceptionFrameStreamUrl() }, 120000)
})
onBeforeUnmount(() => window.clearInterval(refresher))

const detection = computed(() => props.yt.state.value?.detection_status ?? null)
const lockedTarget = computed(() => props.yt.nav.value?.target ?? null)
const objects = computed(() =>
  [...props.yt.detections.value].sort((a, b) => (a.distance_m ?? 99) - (b.distance_m ?? 99)).slice(0, 8))
</script>

<template>
  <section class="panel vision-panel">
    <div class="panel-head">
      <h2 class="panel-title">视觉感知 <small>RGB-D · RKNN</small></h2>
      <span class="pill" :class="detection ? 'tone-ok' : 'tone-muted'">
        {{ detection ? `${detection.model_name ?? '模型'} · ${clock(detection.timestamp)}` : '感知未接入' }}
      </span>
    </div>
    <div class="video">
      <CloudVideoPlayer :api-token="yt.token.value" :fallback-url="frameUrl" :fallback-available="true" />
      <div v-if="lockedTarget" class="lock">目标已锁定 · 地图 ({{ fmt(lockedTarget.x, 2) }}, {{ fmt(lockedTarget.y, 2) }})</div>
    </div>
    <div class="panel-body">
      <table v-if="objects.length" class="objs">
        <thead>
          <tr><th>目标</th><th>颜色</th><th>ID</th><th class="r">距离</th><th class="r">置信度</th></tr>
        </thead>
        <tbody>
          <tr v-for="(o, i) in objects" :key="`${o.track_id ?? 'n'}-${i}`">
            <td>{{ CLASS_LABELS[o.class_name] ?? o.class_name }}</td>
            <td>
              <span v-if="o.color" class="sw"><i :style="{ background: COLOR_SWATCH[o.color] ?? '#888' }"></i>{{ COLOR_LABELS[o.color] ?? o.color }}</span>
              <span v-else class="dim">--</span>
            </td>
            <td class="num dim">{{ o.track_id ?? '--' }}</td>
            <td class="num r">{{ o.distance_m != null ? `${fmt(o.distance_m, 2)} m` : '无深度' }}</td>
            <td class="num r">{{ fmt(o.confidence, 2) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty">视野内暂无目标</p>
    </div>
  </section>
</template>

<style scoped>
.video { position: relative; aspect-ratio: 4 / 3; margin: 0 12px; border-radius: 10px; overflow: hidden; border: 1px solid var(--line); background: #05090d; }
.lock {
  position: absolute; left: 10px; bottom: 10px; padding: 5px 10px; border-radius: 6px; font-size: 12px;
  background: rgba(255, 77, 94, 0.85); color: #fff; font-weight: 600;
}
.video:has(.lock) :deep(.stream-detail) { display: none; }
.panel-body { padding-top: 10px; }
.objs { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; color: var(--text-3); font-weight: 500; font-size: 11px; padding: 4px 6px; border-bottom: 1px solid var(--line); }
td { padding: 6px; border-bottom: 1px solid rgba(120, 180, 200, 0.06); }
.r { text-align: right; }
.dim { color: var(--text-3); }
.sw { display: inline-flex; align-items: center; gap: 5px; }
.sw i { width: 9px; height: 9px; border-radius: 50%; border: 1px solid rgba(255, 255, 255, 0.3); }
</style>
