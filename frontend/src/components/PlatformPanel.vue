<script setup lang="ts">
import { computed } from 'vue'
import { FPGA_MODE_LABELS, FPGA_STATE_LABELS, LOC_LABELS, fmt, linkLabel, linkTone } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const p = computed(() => props.yt.platform.value)
const flag = (v: boolean | null | undefined) => (v == null ? '--' : v ? '正常' : '异常')
const flagTone = (v: boolean | null | undefined) => (v == null ? 'tone-muted' : v ? 'tone-ok' : 'tone-danger')
const roll = computed(() => p.value?.roll_deg ?? 0)
const pitch = computed(() => p.value?.pitch_deg ?? 0)
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h2 class="panel-title">FPGA 平台 <small>NAV · RL CONTROL</small></h2>
      <span class="pill no-dot num">{{ p?.status_rate_hz != null ? `${fmt(p.status_rate_hz, 1)} Hz` : '--' }}</span>
    </div>
    <div class="panel-body">
      <h3><span>导航子系统</span><span class="pill" :class="`tone-${linkTone(p?.nav_link)}`">{{ linkLabel(p?.nav_link) }}</span></h3>
      <div class="kv">
        <div><span>模式</span><strong>{{ FPGA_MODE_LABELS[p?.fpga_mode ?? ''] ?? '--' }}</strong></div>
        <div><span>状态</span><strong :class="{ danger: p?.fpga_state === 'estop' || p?.fpga_state === 'blocked' }">{{ FPGA_STATE_LABELS[p?.fpga_state ?? ''] ?? '--' }}</strong></div>
        <div><span>定位</span><strong>{{ LOC_LABELS[p?.loc_state ?? ''] ?? '--' }}</strong></div>
        <div><span>期望速度</span><strong class="num">{{ fmt(p?.cmd_vx_mps, 2) }} m/s</strong></div>
        <div><span>期望角速度</span><strong class="num">{{ fmt(p?.cmd_wz_radps, 2) }} rad/s</strong></div>
        <div><span>视觉目标</span><strong>{{ p?.target_valid ? '已锁定' : '无' }}</strong></div>
      </div>
      <div class="flags">
        <span class="pill" :class="flagTone(p?.lidar_ok)">雷达 {{ flag(p?.lidar_ok) }}</span>
        <span class="pill" :class="flagTone(p?.odom_ok)">里程计 {{ flag(p?.odom_ok) }}</span>
        <span class="pill" :class="p?.map_loaded ? 'tone-ok' : 'tone-muted'">{{ p?.map_loaded ? '先验图已加载' : '无先验图' }}</span>
      </div>

      <h3><span>运动控制（RL 策略）</span><span class="pill" :class="`tone-${linkTone(p?.control_link)}`">{{ linkLabel(p?.control_link) }}</span></h3>
      <div class="ctl">
        <div class="horizon" :title="`横滚 ${fmt(roll, 1)}°，俯仰 ${fmt(pitch, 1)}°`" aria-hidden="true">
          <div class="sky" :style="{ transform: `rotate(${-roll}deg) translateY(${pitch * 2}px)` }"></div>
          <i class="reticle"></i>
        </div>
        <div class="kv grow">
          <div><span>策略</span><strong :class="{ ok: p?.policy_active }">{{ p?.policy_active == null ? '--' : p.policy_active ? '运行' : '停止' }}</strong></div>
          <div><span>控制急停</span><strong :class="{ danger: p?.control_estop }">{{ p?.control_estop == null ? '--' : p.control_estop ? '锁存' : '无' }}</strong></div>
          <div><span>左 / 右轮</span><strong class="num">{{ fmt(p?.wheel_left_mps, 2) }} / {{ fmt(p?.wheel_right_mps, 2) }}</strong></div>
          <div><span>横滚 / 俯仰</span><strong class="num">{{ fmt(p?.roll_deg, 1) }}° / {{ fmt(p?.pitch_deg, 1) }}°</strong></div>
        </div>
      </div>
      <p v-if="p?.control_faults?.length" class="faults">故障：{{ p.control_faults.join('，') }}</p>
    </div>
  </section>
</template>

<style scoped>
h3 { display: flex; align-items: center; justify-content: space-between; margin: 4px 0 8px; font-size: 12px; color: var(--text-3); font-weight: 600; letter-spacing: 0.06em; }
h3 + .kv { margin-bottom: 8px; }
.flags { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 14px; }
.ctl { display: flex; gap: 10px; align-items: stretch; }
.grow { flex: 1; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.horizon { position: relative; width: 92px; flex: none; border-radius: 50%; aspect-ratio: 1; overflow: hidden; border: 2px solid var(--line-strong); background: #3b2a1c; align-self: center; }
.sky { position: absolute; inset: -50% -50% 50% -50%; background: linear-gradient(180deg, #1b4f7a, #3aa8ff); transform-origin: 50% 100%; transition: transform 0.3s; }
.reticle { position: absolute; left: 22%; right: 22%; top: 50%; height: 2px; background: #ffb547; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.4); }
strong.danger { color: var(--danger); }
strong.ok { color: var(--ok); }
.faults { margin: 10px 0 0; color: var(--danger); font-size: 12px; }
@media (max-width: 640px) {
  .ctl { flex-wrap: wrap; justify-content: center; }
  .horizon { width: 80px; }
  .grow { flex-basis: 100%; }
}
</style>
