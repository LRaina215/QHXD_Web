<script setup lang="ts">
import { computed } from 'vue'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const p = computed(() => props.yt.platform.value)
const up = (link: string | undefined | null) => link === 'online' || link === 'mock'

const layers = computed(() => [
  {
    key: 'rk', title: 'RK3588 任务层', chip: 'Rockchip RK3588 · Ubuntu 22.04',
    items: ['RGB-D 目标检测与三维定位（RKNN NPU）', '离线语音识别 / 理解 / 播报', '任务编排 · Web 中台'],
    live: props.yt.conn.state,
  },
  {
    key: 'link', title: '任务报文', chip: 'NV 协议 · 只发任务不发速度',
    items: ['GOAL / WAYPOINTS / MODE', 'TARGET（机身系 + 时延补偿）', 'STATUS 5 Hz 回传'],
    live: up(p.value?.nav_link),
  },
  {
    key: 'nav', title: 'FPGA 导航', chip: '雷达定位 · 规划 · SAFE 限幅',
    items: ['先验图对准 / 无图里程计', '全局 A* + 局部规划', '探索 · 跟踪 · 安全限速'],
    live: up(p.value?.nav_link),
  },
  {
    key: 'ctl', title: 'FPGA 运动控制', chip: 'RL 策略 · BMI088 姿态',
    items: ['强化学习轮腿策略（片上推理）', '轮速闭环 · 舵机腿部', '急停锁存'],
    live: up(p.value?.control_link),
  },
])
</script>

<template>
  <section class="panel arch">
    <div class="panel-head">
      <h2 class="panel-title">分层架构 <small>SYSTEM ARCHITECTURE</small></h2>
      <span class="pill no-dot">导航与运动控制全部在 FPGA 上</span>
    </div>
    <ol class="panel-body flow">
      <li v-for="(l, i) in layers" :key="l.key" :class="{ live: l.live }">
        <div class="node">
          <header><span class="dot"></span><strong>{{ l.title }}</strong></header>
          <p class="chip">{{ l.chip }}</p>
          <ul><li v-for="it in l.items" :key="it">{{ it }}</li></ul>
        </div>
        <span v-if="i < layers.length - 1" class="arrow" aria-hidden="true"></span>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.flow { list-style: none; margin: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 22px; }
.flow > li { position: relative; }
.node { height: 100%; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--line); background: rgba(255, 255, 255, 0.02); transition: border-color 0.3s, background 0.3s; }
.live .node { border-color: rgba(47, 224, 196, 0.45); background: linear-gradient(180deg, rgba(47, 224, 196, 0.08), rgba(58, 168, 255, 0.03)); }
header { display: flex; align-items: center; gap: 8px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.live .dot { background: var(--ok); box-shadow: 0 0 0 4px rgba(61, 220, 132, 0.15); }
strong { font-size: 14px; }
.chip { margin: 6px 0 8px; font-size: 11px; color: var(--accent); }
ul { margin: 0; padding-left: 16px; color: var(--text-2); font-size: 12px; line-height: 1.7; }
.arrow { position: absolute; right: -18px; top: 50%; width: 14px; height: 14px; border-top: 2px solid var(--line-strong); border-right: 2px solid var(--line-strong); transform: translateY(-50%) rotate(45deg); }
.live .arrow { border-color: var(--accent); }
@media (max-width: 900px) {
  .flow { grid-template-columns: 1fr; gap: 14px; }
  .arrow { right: auto; left: 50%; top: auto; bottom: -13px; transform: translateX(-50%) rotate(135deg); }
}
</style>
