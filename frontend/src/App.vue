<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ArchitecturePanel from './components/ArchitecturePanel.vue'
import MapPanel from './components/MapPanel.vue'
import PlatformPanel from './components/PlatformPanel.vue'
import TaskPanel from './components/TaskPanel.vue'
import TimelinePanel from './components/TimelinePanel.vue'
import TopBar from './components/TopBar.vue'
import VisionPanel from './components/VisionPanel.vue'
import VoiceConfirmDialog from './components/VoiceConfirmDialog.vue'
import VoicePanel from './components/VoicePanel.vue'
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
  <TopBar :yt="yt" />
  <main class="layout">
    <div class="col col-main">
      <MapPanel :yt="yt" :selected="selectedWaypoint" @pick="selectedWaypoint = $event" />
      <TaskPanel v-model:selected="selectedWaypoint" :yt="yt" />
    </div>
    <div class="col col-vision">
      <VisionPanel :yt="yt" />
      <VoicePanel :yt="yt" />
    </div>
    <div class="col col-side">
      <PlatformPanel :yt="yt" />
      <TimelinePanel :yt="yt" />
    </div>
    <ArchitecturePanel class="full" :yt="yt" />
  </main>
  <footer class="foot">
    <span>云拓 · 多模态复杂地形轮腿机器人</span>
    <span>RK3588 任务层 · FPGA 导航与运动控制</span>
  </footer>
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
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr) minmax(300px, 0.8fr);
  gap: 16px;
  padding: 16px 22px 8px;
  max-width: 1920px;
  margin: 0 auto;
}
.col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.col-main > :first-child { flex: 1; }
.col-vision > :first-child, .col-side > :last-child { flex: 1; }
.full { grid-column: 1 / -1; }
.foot { display: flex; justify-content: space-between; gap: 12px; padding: 10px 22px 18px; color: var(--text-3); font-size: 12px; max-width: 1920px; margin: 0 auto; }
@media (max-width: 1440px) {
  .layout { grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); }
  .col-side { grid-column: 1 / -1; display: grid; grid-template-columns: 1fr 1fr; }
}
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; padding: 12px; gap: 12px; }
  .col-side { grid-template-columns: 1fr; }
  .foot { flex-direction: column; padding: 8px 12px 16px; }
}
</style>
