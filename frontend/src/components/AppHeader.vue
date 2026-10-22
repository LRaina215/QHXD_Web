<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { KeyRound, OctagonX } from 'lucide-vue-next'
import { linkLabel, linkTone } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const now = ref(new Date())
const tokenOpen = ref(false)
const tokenDraft = ref(props.yt.token.value)
let timer = 0
onMounted(() => { timer = window.setInterval(() => (now.value = new Date()), 1000) })
onBeforeUnmount(() => window.clearInterval(timer))

const p = computed(() => props.yt.platform.value)
const estopActive = computed(() =>
  p.value?.fpga_state === 'estop' || Boolean(p.value?.control_estop) || Boolean(props.yt.state.value?.device_status.emergency_stop))
const links = computed(() => [
  { key: 'rk', label: 'RK3588', tone: props.yt.conn.state ? 'ok' : 'bad', value: props.yt.conn.state ? '在线' : '重连中' },
  { key: 'nav', label: 'FPGA 导航', tone: linkTone(p.value?.nav_link), value: linkLabel(p.value?.nav_link) },
  { key: 'ctl', label: 'FPGA 控制', tone: linkTone(p.value?.control_link), value: linkLabel(p.value?.control_link) },
  { key: 'cam', label: '视觉', tone: props.yt.state.value?.detection_status ? 'ok' : 'off', value: props.yt.state.value?.detection_status ? '运行' : '未接入' },
])

function saveToken() {
  props.yt.saveToken(tokenDraft.value)
  tokenOpen.value = false
}
</script>

<template>
  <header class="hdr">
    <div class="brand">
      <svg class="mark" viewBox="0 0 40 40" aria-hidden="true">
        <rect width="40" height="40" rx="11" fill="#15171a" />
        <path d="M8 25.5 14.5 17l5 5.2L25.8 12 32 25.5" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />
        <circle cx="14" cy="29.5" r="2.6" fill="#2f5bff" />
        <circle cx="26" cy="29.5" r="2.6" fill="#2f5bff" />
      </svg>
      <div class="name">
        <strong>云拓</strong>
        <span>多模态复杂地形轮腿机器人</span>
      </div>
    </div>

    <ul class="links" aria-label="链路状态">
      <li v-for="l in links" :key="l.key" :class="l.tone">
        <i></i><span class="k">{{ l.label }}</span><span class="v">{{ l.value }}</span>
      </li>
    </ul>

    <div class="right">
      <div class="seg" role="group" aria-label="系统模式">
        <button type="button" :class="{ on: yt.isMock.value }" :aria-pressed="yt.isMock.value" :disabled="yt.busy.mode" @click="yt.switchMode('mock')">模拟</button>
        <button type="button" :class="{ on: !yt.isMock.value }" :aria-pressed="!yt.isMock.value" :disabled="yt.busy.mode" @click="yt.switchMode('real')">实车</button>
      </div>
      <button type="button" class="icon-btn" :class="{ set: yt.token.value }" :title="yt.token.value ? '已设置访问 Token' : '设置公网访问 Token'"
        :aria-label="yt.token.value ? '已设置访问 Token' : '设置公网访问 Token'" @click="tokenOpen = !tokenOpen">
        <KeyRound :size="18" />
      </button>
      <time class="clock num">{{ now.toLocaleTimeString('zh-CN', { hour12: false }) }}</time>
      <button type="button" class="estop" :class="{ active: estopActive }" :disabled="yt.busy.estop" @click="yt.estop(!estopActive)">
        <OctagonX :size="20" :stroke-width="2.4" />
        <span>{{ estopActive ? '解除急停' : '急停' }}</span>
      </button>
    </div>

    <button type="button" class="estop-fab" :class="{ active: estopActive }" :disabled="yt.busy.estop"
      :aria-label="estopActive ? '解除急停' : '急停'" @click="yt.estop(!estopActive)">
      <OctagonX :size="22" :stroke-width="2.4" />
      <span>{{ estopActive ? '解除' : '急停' }}</span>
    </button>

    <form v-if="tokenOpen" class="token card" @submit.prevent="saveToken">
      <label class="label" for="tk">公网访问 Token（只保存在本浏览器）</label>
      <div class="row">
        <input id="tk" v-model="tokenDraft" class="field" type="password" autocomplete="off" />
        <button type="submit" class="btn primary">保存</button>
      </div>
    </form>
  </header>
</template>

<style scoped>
.hdr {
  position: sticky; top: 0; z-index: 30;
  display: flex; align-items: center; gap: 24px; height: 68px; padding: 0 28px;
  background: rgba(242, 241, 236, 0.86); backdrop-filter: saturate(1.4) blur(14px);
  border-bottom: 1px solid var(--line);
}
.brand { display: flex; align-items: center; gap: 12px; flex: none; }
.mark { width: 38px; height: 38px; }
.name { display: flex; flex-direction: column; line-height: 1.15; }
.name strong { font-size: 18px; font-weight: 750; letter-spacing: 0.02em; }
.name span { font-size: 12px; color: var(--ink-3); font-weight: 500; }
.links { display: flex; gap: 4px; margin: 0 auto; padding: 4px; list-style: none; background: var(--surface); border-radius: 999px; box-shadow: var(--shadow); }
.links li { display: flex; align-items: center; gap: 7px; height: 30px; padding: 0 12px; border-radius: 999px; font-size: 13px; white-space: nowrap; }
.links i { width: 7px; height: 7px; border-radius: 50%; background: var(--off); }
.links .k { color: var(--ink-2); font-weight: 500; }
.links .v { font-weight: 650; }
.links .ok i { background: var(--ok); box-shadow: 0 0 0 3px var(--ok-soft); } .links .ok .v { color: var(--ok); }
.links .bad i { background: var(--bad); box-shadow: 0 0 0 3px var(--bad-soft); } .links .bad .v { color: var(--bad); }
.links .mock i { background: var(--mock); box-shadow: 0 0 0 3px var(--mock-soft); } .links .mock .v { color: var(--mock); }
.links .off .v { color: var(--off); }
.right { display: flex; align-items: center; gap: 12px; flex: none; }
.seg { display: inline-flex; padding: 3px; border-radius: 12px; background: var(--surface-3); }
.seg button { height: 34px; padding: 0 14px; border: 0; border-radius: 9px; background: transparent; color: var(--ink-2); font-size: 13px; font-weight: 600; }
.seg button.on { background: var(--surface); color: var(--ink); box-shadow: var(--shadow); }
.icon-btn { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 12px; border: 0; background: transparent; color: var(--ink-3); }
.icon-btn:hover { background: var(--surface-3); color: var(--ink); }
.icon-btn.set { color: var(--ok); }
.clock { font-size: 14px; font-weight: 600; color: var(--ink-2); min-width: 66px; text-align: right; }
.estop {
  display: inline-flex; align-items: center; gap: 8px; height: 44px; padding: 0 20px; border: 0; border-radius: 12px;
  background: var(--bad); color: #fff; font-size: 15px; font-weight: 750; letter-spacing: 0.12em;
  box-shadow: 0 2px 0 #b3182a, 0 6px 18px rgba(229, 38, 59, 0.32);
}
.estop:hover:not(:disabled) { background: #d01c30; }
.estop.active { background: #15171a; box-shadow: 0 0 0 3px var(--bad), 0 6px 18px rgba(229, 38, 59, 0.3); animation: ring 1.4s infinite; }
@keyframes ring { 50% { box-shadow: 0 0 0 6px rgba(229, 38, 59, 0.35); } }
.token { position: absolute; right: 28px; top: 74px; width: 360px; padding: 16px; box-shadow: var(--shadow-lift); }
.token .row { display: flex; gap: 8px; }
@media (max-width: 1280px) { .name span { display: none; } }
@media (max-width: 1080px) {
  .hdr { flex-wrap: wrap; height: auto; padding: 10px 16px; gap: 10px 16px; }
  .right { margin-left: auto; }
  .links { order: 3; width: 100%; margin: 0; overflow-x: auto; justify-content: flex-start; }
}
.links { scrollbar-width: none; }
.links::-webkit-scrollbar { display: none; }
.estop-fab { display: none; }
@media (max-width: 560px) {
  /* 手机：头部随页面滚走，急停改为常驻右下角的悬浮按钮 */
  .hdr { position: static; backdrop-filter: none; background: var(--canvas); }
  .clock, .icon-btn, .right .estop { display: none; }
  .seg button { padding: 0 12px; }
  .links li { padding: 0 10px; font-size: 12px; }
  .estop-fab {
    position: fixed; right: 16px; bottom: calc(18px + env(safe-area-inset-bottom)); z-index: 40;
    display: grid; place-items: center; gap: 0; width: 68px; height: 68px; border-radius: 50%; border: 0;
    background: var(--bad); color: #fff; font-size: 13px; font-weight: 750; letter-spacing: 0.08em;
    box-shadow: 0 3px 0 #b3182a, 0 10px 26px rgba(229, 38, 59, 0.42);
  }
  .estop-fab.active { background: #15171a; box-shadow: 0 0 0 3px var(--bad), 0 10px 26px rgba(229, 38, 59, 0.4); }
}
</style>
