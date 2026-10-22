<script setup lang="ts">
import { computed, ref } from 'vue'
import { Armchair, Backpack, ChevronRight, CupSoda, Footprints, House, MapPin, Milk, Navigation, Route, ScanSearch, User, Volleyball } from 'lucide-vue-next'
import { COLOR_LABELS, COLOR_SWATCH, targetLabel } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const selected = defineModel<string>('selected', { required: true })
const tab = ref<'vision' | 'goto' | 'patrol'>('vision')
const cls = ref('bottle')
const color = ref<string | null>('red')
const classes = [
  { id: 'bottle', name: '水瓶', icon: Milk }, { id: 'cup', name: '杯子', icon: CupSoda }, { id: 'person', name: '人', icon: User },
  { id: 'sports ball', name: '球', icon: Volleyball }, { id: 'chair', name: '椅子', icon: Armchair }, { id: 'backpack', name: '背包', icon: Backpack },
]
const colors = ['red', 'green', 'blue', 'yellow', 'white', 'black']
const active = computed(() => ['pending', 'running', 'paused'].includes(props.yt.state.value?.task_status.state ?? ''))
const locked = computed(() => active.value || props.yt.busy.mission)
const points = computed(() => props.yt.waypoints.value.filter((w) => w.configured))
const route = computed(() => points.value.filter((w) => w.group === 'patrol'))
const label = computed(() => targetLabel(cls.value, color.value))
</script>

<template>
  <section class="card cmd">
    <div class="card-head">
      <div class="tabs" role="tablist" aria-label="任务类型">
        <button type="button" role="tab" :aria-selected="tab === 'vision'" :class="{ on: tab === 'vision' }" @click="tab = 'vision'"><ScanSearch :size="16" />视觉任务</button>
        <button type="button" role="tab" :aria-selected="tab === 'goto'" :class="{ on: tab === 'goto' }" @click="tab = 'goto'"><Navigation :size="16" />定点</button>
        <button type="button" role="tab" :aria-selected="tab === 'patrol'" :class="{ on: tab === 'patrol' }" @click="tab = 'patrol'"><Route :size="16" />巡检</button>
      </div>
    </div>

    <div v-if="tab === 'vision'" class="card-body">
      <span class="label">找什么</span>
      <div class="classes">
        <button v-for="c in classes" :key="c.id" type="button" class="cls" :class="{ on: cls === c.id }" :aria-pressed="cls === c.id" @click="cls = c.id">
          <component :is="c.icon" :size="22" :stroke-width="1.8" /><span>{{ c.name }}</span>
        </button>
      </div>
      <span class="label">什么颜色 <em>可不选</em></span>
      <div class="colors">
        <button v-for="c in colors" :key="c" type="button" class="sw" :class="{ on: color === c }" :aria-pressed="color === c"
          :aria-label="`${COLOR_LABELS[c]}色`" :title="`${COLOR_LABELS[c]}色`" @click="color = color === c ? null : c">
          <i :style="{ background: COLOR_SWATCH[c] }"></i>
        </button>
      </div>
      <button type="button" class="btn primary go" :disabled="locked" @click="yt.searchTarget(cls, color, label)">
        <ScanSearch :size="18" />寻找{{ label }}并停在旁边
      </button>
      <button type="button" class="btn go-2" :disabled="locked" @click="yt.followMe()">
        <Footprints :size="18" />跟随我
      </button>
      <p class="hint">FPGA 自主探索，发现目标后接近到 0.7 m 并转向面对它。</p>
    </div>

    <div v-else-if="tab === 'goto'" class="card-body">
      <ul class="points" role="radiogroup" aria-label="目标点">
        <li v-for="w in points" :key="w.waypoint_id">
          <button type="button" role="radio" :aria-checked="selected === w.waypoint_id" :class="{ on: selected === w.waypoint_id }" @click="selected = w.waypoint_id">
            <component :is="w.waypoint_id === 'home' ? House : MapPin" :size="18" />
            <span class="nm">{{ w.name }}</span>
            <span class="xy num">{{ w.pose ? `${w.pose.x.toFixed(1)}, ${w.pose.y.toFixed(1)}` : '--' }}</span>
          </button>
        </li>
      </ul>
      <button type="button" class="btn primary go" :disabled="locked || !selected" @click="yt.goTo(selected)">
        <Navigation :size="18" />前往 {{ points.find((w) => w.waypoint_id === selected)?.name ?? '' }}
      </button>
      <p class="hint">也可以直接点场地图上的点位来选择。</p>
    </div>

    <div v-else class="card-body">
      <ol class="chain">
        <li v-for="w in route" :key="w.waypoint_id"><span>{{ w.name }}</span><ChevronRight :size="16" /></li>
        <li><span>起点</span></li>
      </ol>
      <button type="button" class="btn primary go" :disabled="locked || !route.length" @click="yt.mission('start_patrol', { patrol_id: 'default_patrol' })">
        <Route :size="18" />开始巡检
      </button>
      <p class="hint">逐点导航，每个点停留后继续，最后返回起点。</p>
    </div>
  </section>
</template>

<style scoped>
.tabs { display: flex; gap: 4px; padding: 3px; border-radius: 12px; background: var(--surface-3); width: 100%; }
.tabs button { flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 36px; border: 0; border-radius: 9px; background: transparent; color: var(--ink-2); font-size: 13px; font-weight: 600; }
.tabs button.on { background: var(--surface); color: var(--ink); box-shadow: var(--shadow); }
.label em { font-style: normal; color: var(--ink-3); font-weight: 500; margin-left: 4px; }
.classes { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-bottom: 16px; }
.cls { display: grid; justify-items: center; gap: 4px; padding: 10px 0 8px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); font-size: 12px; font-weight: 600; }
.cls:hover { border-color: var(--ink-3); }
.cls.on { border-color: var(--brand); background: var(--brand-soft); color: var(--brand-deep); }
.colors { display: flex; gap: 10px; margin-bottom: 18px; }
.sw { width: 34px; height: 34px; padding: 3px; border-radius: 50%; border: 2px solid transparent; background: transparent; }
.sw i { display: block; width: 100%; height: 100%; border-radius: 50%; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12); }
.sw.on { border-color: var(--ink); }
.go { width: 100%; height: 48px; font-size: 15px; }
.go-2 { width: 100%; margin-top: 8px; }
.hint { margin: 10px 0 0; font-size: 12px; color: var(--ink-3); }
.points { list-style: none; margin: 0 0 14px; padding: 0; display: grid; gap: 6px; }
.points button { width: 100%; display: flex; align-items: center; gap: 10px; height: 46px; padding: 0 14px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); text-align: left; }
.points button.on { border-color: var(--brand); background: var(--brand-soft); color: var(--brand-deep); }
.nm { flex: 1; font-weight: 600; color: var(--ink); }
.on .nm { color: var(--brand-deep); }
.xy { font-size: 12px; color: var(--ink-3); }
.chain { list-style: none; margin: 4px 0 18px; padding: 14px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 2px; border-radius: 12px; background: var(--surface-2); }
.chain li { display: inline-flex; align-items: center; gap: 2px; color: var(--ink-3); }
.chain span { padding: 4px 10px; border-radius: 999px; background: var(--surface); color: var(--ink); font-size: 13px; font-weight: 600; box-shadow: var(--shadow); }
@media (max-width: 420px) { .classes { grid-template-columns: repeat(3, 1fr); } }
</style>
