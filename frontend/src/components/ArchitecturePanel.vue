<script setup lang="ts">
import { computed } from 'vue'
import { BrainCircuit, Cpu, Layers, Radar, Waypoints } from 'lucide-vue-next'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const p = computed(() => props.yt.platform.value)
const up = (link: string | undefined | null) => link === 'online' || link === 'mock'

const layers = computed(() => [
  { key: 'rk', icon: BrainCircuit, title: 'RK3588 任务层', sub: '感知 · 语音 · 任务编排', items: ['RGB-D 目标检测与三维定位', '离线语音识别与理解', 'Web 控制台'], live: props.yt.conn.state },
  { key: 'link', icon: Waypoints, title: '任务报文', sub: '只发任务，不发速度', items: ['目标点 · 模式 · 视觉目标', '时延补偿的机身系目标', '状态 5 Hz 回传'], live: up(p.value?.nav_link) },
  { key: 'nav', icon: Radar, title: 'FPGA 导航', sub: '定位 · 规划 · 安全限速', items: ['先验图对准 / 里程计', '全局 + 局部规划', '探索与跟踪'], live: up(p.value?.nav_link) },
  { key: 'ctl', icon: Cpu, title: 'FPGA 运动控制', sub: '强化学习轮腿策略', items: ['片上策略推理', '轮速闭环 · 腿部舵机', 'BMI088 姿态 · 急停锁存'], live: up(p.value?.control_link) },
])
</script>

<template>
  <section class="card arch">
    <div class="card-head">
      <h2 class="card-title"><Layers :size="17" />系统架构</h2>
      <span class="spacer"></span>
      <span class="eyebrow">导航与运动控制全部在 FPGA 上实现</span>
    </div>
    <ol class="card-body flow">
      <li v-for="l in layers" :key="l.key" :class="{ live: l.live }">
        <div class="ico"><component :is="l.icon" :size="20" /></div>
        <div class="txt">
          <strong>{{ l.title }}</strong>
          <span class="sub">{{ l.sub }}</span>
          <ul><li v-for="it in l.items" :key="it">{{ it }}</li></ul>
        </div>
        <span class="state"><i></i>{{ l.live ? '运行' : '未接入' }}</span>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.flow { list-style: none; margin: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; counter-reset: s; }
.flow > li { position: relative; display: grid; grid-template-columns: auto 1fr; gap: 12px; padding: 4px 22px 4px 0; }
.flow > li + li { padding-left: 22px; border-left: 1px solid var(--line); }
.ico { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; background: var(--surface-3); color: var(--ink-2); }
.live .ico { background: var(--ink); color: #fff; }
.txt { display: grid; gap: 2px; min-width: 0; }
.txt strong { font-size: 15px; font-weight: 650; }
.sub { font-size: 12px; color: var(--brand-deep); font-weight: 600; }
.txt ul { margin: 6px 0 0; padding: 0; list-style: none; display: grid; gap: 2px; }
.txt ul li { font-size: 12px; color: var(--ink-2); }
.state { position: absolute; top: 4px; right: 22px; display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; color: var(--ink-3); }
.state i { width: 6px; height: 6px; border-radius: 50%; background: var(--off); }
.live .state { color: var(--ok); }
.live .state i { background: var(--ok); }
@media (max-width: 1100px) {
  .flow { grid-template-columns: 1fr 1fr; row-gap: 18px; }
  .flow > li:nth-child(3) { border-left: 0; padding-left: 0; }
}
@media (max-width: 600px) {
  .flow { grid-template-columns: 1fr; }
  .flow > li, .flow > li + li { border-left: 0; padding: 0 0 14px; }
  .flow > li + li { border-top: 1px solid var(--line); padding-top: 14px; }
  .state { right: 0; }
  .flow > li + li .state { top: 18px; }
}
</style>
