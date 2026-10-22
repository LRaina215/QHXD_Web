<script setup lang="ts">
import { computed } from 'vue'
import { Check, Cpu, X } from 'lucide-vue-next'
import { FPGA_MODE_LABELS, FPGA_STATE_LABELS, LOC_LABELS, fmt, linkLabel, linkTone } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const p = computed(() => props.yt.platform.value)
const flags = computed(() => [
  { k: '雷达', v: p.value?.lidar_ok }, { k: '里程计', v: p.value?.odom_ok },
  { k: '先验图', v: p.value ? p.value.map_loaded : null }, { k: '视觉目标', v: p.value ? p.value.target_valid : null },
])
const wheelPct = (v: number | null | undefined) => `${Math.min(100, Math.abs(v ?? 0) / 0.6 * 100)}%`
const stateTone = computed(() => {
  const s = p.value?.fpga_state
  if (s === 'estop' || s === 'blocked') return 'bad'
  if (s === 'moving' || s === 'tracking' || s === 'searching') return 'run'
  if (s === 'arrived') return 'ok'
  return 'off'
})
</script>

<template>
  <section class="card tel">
    <div class="card-head">
      <h2 class="card-title"><Cpu :size="17" />FPGA 平台</h2>
      <span class="spacer"></span>
      <span class="tag" :class="linkTone(p?.nav_link)"><i class="dot"></i>导航 · {{ linkLabel(p?.nav_link) }}</span>
    </div>
    <div class="card-body">
      <div class="big">
        <div>
          <span class="eyebrow">导航状态</span>
          <strong :class="stateTone">{{ FPGA_STATE_LABELS[p?.fpga_state ?? ''] ?? '--' }}</strong>
          <small>{{ FPGA_MODE_LABELS[p?.fpga_mode ?? ''] ?? '--' }}模式</small>
        </div>
        <div>
          <span class="eyebrow">期望速度</span>
          <strong class="num">{{ fmt(p?.cmd_vx_mps, 2) }}</strong>
          <small class="num">m/s · ω {{ fmt(p?.cmd_wz_radps, 2) }}</small>
        </div>
        <div>
          <span class="eyebrow">定位</span>
          <strong>{{ LOC_LABELS[p?.loc_state ?? '']?.replace('（里程计）', '') ?? '--' }}</strong>
          <small class="num">{{ p?.loc_quality != null ? `质量 ${p.loc_quality}%` : `${fmt(p?.status_rate_hz, 1)} Hz` }}</small>
        </div>
      </div>
      <ul class="flags">
        <li v-for="f in flags" :key="f.k" :class="f.v == null ? 'na' : f.v ? 'yes' : 'no'">
          <Check v-if="f.v" :size="14" :stroke-width="3" /><X v-else :size="14" :stroke-width="3" />{{ f.k }}
        </li>
      </ul>

      <div class="ctl-head">
        <span class="eyebrow">运动控制 · RL 策略</span>
        <span class="tag" :class="linkTone(p?.control_link)"><i class="dot"></i>{{ linkLabel(p?.control_link) }}</span>
      </div>
      <div class="ctl">
        <div class="wheels">
          <div><span>左轮</span><div class="wb"><i :style="{ width: wheelPct(p?.wheel_left_mps) }"></i></div><b class="num">{{ fmt(p?.wheel_left_mps, 2) }}</b></div>
          <div><span>右轮</span><div class="wb"><i :style="{ width: wheelPct(p?.wheel_right_mps) }"></i></div><b class="num">{{ fmt(p?.wheel_right_mps, 2) }}</b></div>
        </div>
        <div class="att" :title="`横滚 ${fmt(p?.roll_deg, 1)}°，俯仰 ${fmt(p?.pitch_deg, 1)}°`">
          <svg viewBox="0 0 64 64" aria-hidden="true">
            <circle cx="32" cy="32" r="29" fill="#f7f6f2" stroke="#d6d3ca" stroke-width="2" />
            <g :transform="`rotate(${-(p?.roll_deg ?? 0)} 32 32) translate(0 ${(p?.pitch_deg ?? 0) * 1.2})`">
              <line x1="10" y1="32" x2="54" y2="32" stroke="#15171a" stroke-width="3" stroke-linecap="round" />
              <circle cx="32" cy="32" r="3.5" fill="#2f5bff" />
            </g>
          </svg>
          <span class="num">{{ fmt(p?.roll_deg, 1) }}° / {{ fmt(p?.pitch_deg, 1) }}°</span>
        </div>
      </div>
      <div class="foot">
        <span :class="p?.policy_active ? 'okt' : ''">策略{{ p?.policy_active == null ? ' --' : p.policy_active ? '运行中' : '已停止' }}</span>
        <span :class="p?.control_estop ? 'badt' : ''">控制急停{{ p?.control_estop == null ? ' --' : p.control_estop ? '锁存' : '未触发' }}</span>
        <span v-if="p?.control_faults?.length" class="badt">故障：{{ p.control_faults.join('，') }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.big { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.big > div { display: grid; gap: 2px; min-width: 0; }
.big strong { font-size: 24px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.2; white-space: nowrap; }
.big strong.run { color: var(--run); } .big strong.ok { color: var(--ok); } .big strong.bad { color: var(--bad); }
.big small { font-size: 12px; color: var(--ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.flags { display: flex; flex-wrap: wrap; gap: 6px; list-style: none; margin: 14px 0 18px; padding: 0; }
.flags li { display: inline-flex; align-items: center; gap: 4px; height: 26px; padding: 0 10px; border-radius: 999px; font-size: 12px; font-weight: 600; background: var(--surface-2); color: var(--ink-3); }
.flags .yes { background: var(--ok-soft); color: var(--ok); }
.flags .no { background: var(--surface-2); color: var(--ink-3); }
.ctl-head { display: flex; align-items: center; justify-content: space-between; padding-top: 14px; border-top: 1px solid var(--line); }
.ctl { display: flex; gap: 16px; align-items: center; margin-top: 10px; }
.wheels { flex: 1; display: grid; gap: 10px; }
.wheels > div { display: grid; grid-template-columns: 34px 1fr 46px; align-items: center; gap: 10px; font-size: 12px; color: var(--ink-2); }
.wb { height: 6px; border-radius: 999px; background: var(--surface-3); overflow: hidden; }
.wb i { display: block; height: 100%; border-radius: inherit; background: var(--ink); transition: width 0.3s; }
.wheels b { text-align: right; font-size: 13px; color: var(--ink); }
.att { display: grid; justify-items: center; gap: 4px; font-size: 11px; color: var(--ink-3); }
.att svg { width: 64px; height: 64px; }
.foot { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 12px; font-size: 12px; color: var(--ink-3); font-weight: 550; }
.okt { color: var(--ok); } .badt { color: var(--bad); }
</style>
