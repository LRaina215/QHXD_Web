<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CircleAlert, CircleCheck, Info } from 'lucide-vue-next'
import ActivityCard from './components/ActivityCard.vue'
import AppHeader from './components/AppHeader.vue'
import ArchitecturePanel from './components/ArchitecturePanel.vue'
import CommandCard from './components/CommandCard.vue'
import MissionHero from './components/MissionHero.vue'
import ObjectsCard from './components/ObjectsCard.vue'
import StageCard from './components/StageCard.vue'
import TelemetryCard from './components/TelemetryCard.vue'
import VoiceCard from './components/VoiceCard.vue'
import VoiceConfirmDialog from './components/VoiceConfirmDialog.vue'
import { useYunTuo } from './composables/useYunTuo'

const yt = useYunTuo()
const selectedWaypoint = ref('')

watch(yt.waypoints, (list) => {
  if (!list.some((w) => w.waypoint_id === selectedWaypoint.value)) {
    selectedWaypoint.value = list.find((w) => w.configured && w.waypoint_id !== 'home')?.waypoint_id ?? list[0]?.waypoint_id ?? ''
  }
})

onMounted(() => void yt.start())
onBeforeUnmount(() => yt.stop())
</script>

<template>
  <AppHeader :yt="yt" />
  <main class="page">
    <MissionHero class="a-hero" :yt="yt" />
    <StageCard class="a-stage" :yt="yt" :selected="selectedWaypoint" @pick="selectedWaypoint = $event" />
    <div class="a-side">
      <CommandCard v-model:selected="selectedWaypoint" :yt="yt" />
      <VoiceCard :yt="yt" />
    </div>
    <TelemetryCard class="a-tel" :yt="yt" />
    <ObjectsCard class="a-obj" :yt="yt" />
    <ActivityCard class="a-act" :yt="yt" />
    <ArchitecturePanel class="a-arch" :yt="yt" />
  </main>
  <footer class="foot">
    <span>云拓 · 多模态复杂地形轮腿机器人</span>
    <span>全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道</span>
  </footer>

  <Transition name="toast">
    <div v-if="yt.toast.value" :key="yt.toast.value.id" class="toast" :class="yt.toast.value.tone" role="status">
      <CircleCheck v-if="yt.toast.value.tone === 'ok'" :size="18" />
      <CircleAlert v-else-if="['bad', 'warn', 'wait'].includes(yt.toast.value.tone)" :size="18" />
      <Info v-else :size="18" />
      <span>{{ yt.toast.value.text }}</span>
    </div>
  </Transition>

  <VoiceConfirmDialog
    v-if="yt.pending.value"
    :result="yt.pending.value"
    :loading="yt.busy.confirm"
    :error="yt.confirmError.value"
    @confirm="yt.confirm(true)"
    @cancel="yt.confirm(false)"
    @close="yt.pending.value = null"
  />
</template>

<style scoped>
.page {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  grid-template-areas:
    "hero hero hero hero hero hero hero hero hero hero hero hero"
    "stage stage stage stage stage stage stage stage side side side side"
    "tel tel tel tel obj obj obj obj act act act act"
    "arch arch arch arch arch arch arch arch arch arch arch arch";
  gap: 20px;
  max-width: 1680px;
  margin: 0 auto;
  padding: 24px 28px 8px;
}
.a-hero { grid-area: hero; }
.a-stage { grid-area: stage; min-height: clamp(460px, calc(100vh - 290px), 720px); }
.a-side { grid-area: side; display: flex; flex-direction: column; gap: 20px; min-width: 0; }
.a-side > :last-child { flex: 1; }
.a-tel { grid-area: tel; }
.a-obj { grid-area: obj; }
.a-act { grid-area: act; }
.a-arch { grid-area: arch; }
.foot { display: flex; justify-content: space-between; gap: 16px; max-width: 1680px; margin: 0 auto; padding: 12px 28px 28px; color: var(--ink-3); font-size: 12px; }
.toast {
  position: fixed; left: 50%; bottom: 28px; z-index: 60; transform: translateX(-50%);
  display: flex; align-items: center; gap: 10px; max-width: min(640px, calc(100vw - 32px));
  padding: 12px 18px; border-radius: 14px; background: var(--ink); color: #fff; font-size: 14px; font-weight: 550;
  box-shadow: 0 12px 40px rgba(21, 23, 26, 0.3);
}
.toast.ok svg { color: #4ade80; }
.toast.bad svg, .toast.warn svg { color: #ff6b7a; }
.toast.wait svg { color: #fbbf24; }
.toast.run svg, .toast.mock svg, .toast.off svg { color: #8ea6ff; }
.toast-enter-active, .toast-leave-active { transition: opacity 0.2s, transform 0.2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, 8px); }
@media (max-width: 1280px) {
  .page {
    grid-template-areas:
      "hero hero hero hero hero hero hero hero hero hero hero hero"
      "stage stage stage stage stage stage stage side side side side side"
      "tel tel tel tel tel tel obj obj obj obj obj obj"
      "act act act act act act act act act act act act"
      "arch arch arch arch arch arch arch arch arch arch arch arch";
  }
}
@media (max-width: 960px) {
  .page { grid-template-columns: 1fr; grid-template-areas: "hero" "stage" "side" "tel" "obj" "act" "arch"; gap: 14px; padding: 14px; }
  .a-stage { min-height: 0; height: auto; aspect-ratio: 4 / 3.6; width: 100%; }
  .a-side { gap: 14px; }
  .foot { flex-direction: column; gap: 4px; padding: 8px 14px 100px; }
}
@media (max-width: 560px) {
  .toast { bottom: calc(100px + env(safe-area-inset-bottom)); }
}
</style>
