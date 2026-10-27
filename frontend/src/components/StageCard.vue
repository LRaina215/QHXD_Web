<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowLeftRight, Crosshair, Map as MapIcon, Video } from 'lucide-vue-next'
import CloudVideoPlayer from './CloudVideoPlayer.vue'
import FieldMap from './FieldMap.vue'
import MapUpload from './MapUpload.vue'
import { perceptionFrameStreamUrl } from '../config/api'
import { LOC_LABELS, fmt } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo; selected: string }>()
const emit = defineEmits<{ pick: [waypointId: string] }>()
const main = ref<'map' | 'cam'>('map')
const frameUrl = ref(perceptionFrameStreamUrl())
let refresher = 0
onMounted(() => { refresher = window.setInterval(() => { frameUrl.value = perceptionFrameStreamUrl() }, 120000) })
onBeforeUnmount(() => window.clearInterval(refresher))

const p = computed(() => props.yt.platform.value)
const target = computed(() => props.yt.nav.value?.target ?? null)
const mapless = computed(() => !props.yt.mapMeta.value || props.yt.mapMeta.value.version.startsWith('canvas'))
const pose = computed(() => props.yt.nav.value?.pose ?? null)
const hud = computed(() => [
  { k: '速度', v: fmt(p.value?.cmd_vx_mps, 2), u: 'm/s' },
  { k: '角速度', v: fmt(p.value?.cmd_wz_radps, 2), u: 'rad/s' },
  { k: '位姿', v: pose.value ? `${fmt(pose.value.x, 2)}, ${fmt(pose.value.y, 2)}` : '--', u: pose.value ? `${fmt((pose.value.yaw * 180) / Math.PI, 0)}°` : '' },
  { k: '定位', v: LOC_LABELS[p.value?.loc_state ?? ''] ?? '--', u: p.value?.loc_quality != null ? `${p.value.loc_quality}%` : '' },
])
</script>

<template>
  <section class="stage">
    <header class="bar">
      <div class="seg" role="tablist" aria-label="主视图">
        <button type="button" role="tab" :aria-selected="main === 'map'" :class="{ on: main === 'map' }" @click="main = 'map'">
          <MapIcon :size="16" />场地
        </button>
        <button type="button" role="tab" :aria-selected="main === 'cam'" :class="{ on: main === 'cam' }" @click="main = 'cam'">
          <Video :size="16" />相机
        </button>
      </div>
      <span class="ctx">{{ main === 'map' ? (yt.mapPreview.value ? '地图预览 · 未下发FPGA' : mapless ? '无先验图 · 里程计坐标系' : '先验地图坐标系') : 'Orbbec Astra Pro Plus · RKNN 检测' }}</span>
      <MapUpload :yt="yt" />
      <span v-if="target" class="lock"><Crosshair :size="15" />目标已锁定</span>
    </header>

    <div class="views">
      <div class="view" :class="main === 'cam' ? 'main' : 'pip'" @click="main !== 'cam' && (main = 'cam')">
        <CloudVideoPlayer :api-token="yt.token.value" :fallback-url="frameUrl" :fallback-available="true" />
        <span v-if="main !== 'cam'" class="pip-label"><Video :size="13" />相机<ArrowLeftRight :size="13" /></span>
      </div>
      <div class="view" :class="main === 'map' ? 'main' : 'pip'" @click="main !== 'map' && (main = 'map')">
        <FieldMap :yt="yt" :selected="selected" :compact="main !== 'map'" @pick="emit('pick', $event)" />
        <span v-if="main !== 'map'" class="pip-label"><MapIcon :size="13" />场地<ArrowLeftRight :size="13" /></span>
      </div>
      <dl class="hud">
        <div v-for="h in hud" :key="h.k"><dt>{{ h.k }}</dt><dd class="num">{{ h.v }}<small>{{ h.u }}</small></dd></div>
      </dl>
    </div>
  </section>
</template>

<style scoped>
.stage { display: flex; flex-direction: column; min-height: 0; min-width: 0; border-radius: var(--r-lg); background: var(--stage); color: var(--stage-ink); overflow: hidden; box-shadow: var(--shadow-lift); }
.bar { display: flex; align-items: center; gap: 14px; padding: 12px 14px; border-bottom: 1px solid var(--stage-line); }
.seg { display: inline-flex; padding: 3px; border-radius: 11px; background: rgba(255, 255, 255, 0.06); }
.seg button { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 14px; border: 0; border-radius: 8px; background: transparent; color: var(--stage-ink-2); font-size: 13px; font-weight: 600; }
.seg button.on { background: rgba(255, 255, 255, 0.14); color: #fff; }
.ctx { font-size: 13px; color: var(--stage-ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lock { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 12px; border-radius: 999px; background: rgba(229, 38, 59, 0.18); color: #ff8a96; font-size: 12px; font-weight: 650; white-space: nowrap; }
.views { position: relative; flex: 1; min-height: 0; }
.view { position: absolute; overflow: hidden; transition: all 0.35s cubic-bezier(.2, .8, .2, 1); }
.view.main { inset: 0; }
.view.pip {
  right: 16px; bottom: 16px; width: min(34%, 300px); aspect-ratio: 4 / 3; z-index: 3; cursor: pointer;
  border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.16); background: var(--stage-2);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
}
.view.pip:hover { border-color: rgba(255, 255, 255, 0.4); }
.view.pip :deep(.stream-mode-plate), .view.pip :deep(.stream-detail), .view.pip :deep(.stream-retry), .view.pip :deep(.cloud-video-placeholder) { display: none; }
.view.main :deep(.stream-detail) { display: none; }
.pip-label { position: absolute; left: 8px; top: 8px; display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 9px; border-radius: 999px; background: rgba(15, 18, 22, 0.78); color: #fff; font-size: 12px; font-weight: 600; z-index: 2; }
.hud { position: absolute; left: 16px; bottom: 16px; z-index: 2; display: flex; gap: 8px; margin: 0; pointer-events: none; flex-wrap: wrap; max-width: calc(66% - 24px); }
.hud > div { padding: 8px 12px; border-radius: 12px; background: rgba(15, 18, 22, 0.72); backdrop-filter: blur(8px); border: 1px solid var(--stage-line); min-width: 96px; }
.hud dt { font-size: 11px; color: var(--stage-ink-2); font-weight: 550; }
.hud dd { margin: 2px 0 0; font-size: 16px; font-weight: 650; color: #fff; white-space: nowrap; }
.hud small { font-size: 11px; color: var(--stage-ink-2); margin-left: 4px; font-weight: 550; }
@media (max-width: 720px) {
  .ctx { display: none; }
  .view.pip { width: 36%; right: 10px; top: 10px; bottom: auto; }
  .hud { left: 10px; bottom: 10px; max-width: calc(58% - 20px); gap: 6px; }
  .hud > div { min-width: 0; padding: 6px 9px; }
  .hud > div:nth-child(n + 3) { display: none; }
  .hud dd { font-size: 14px; }
}
</style>
