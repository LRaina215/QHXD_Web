<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { linkLabel, linkTone } from '../labels'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const now = ref(new Date())
const tokenOpen = ref(false)
const tokenDraft = ref(props.yt.token.value)
let timer = 0

onMounted(() => { timer = window.setInterval(() => (now.value = new Date()), 1000) })
onBeforeUnmount(() => window.clearInterval(timer))

const platform = computed(() => props.yt.platform.value)
const estopActive = computed(() =>
  platform.value?.fpga_state === 'estop' || Boolean(platform.value?.control_estop) || Boolean(props.yt.state.value?.device_status.emergency_stop))

const links = computed(() => [
  { key: 'rk', label: 'RK3588', tone: props.yt.conn.state ? 'ok' : 'danger', value: props.yt.conn.state ? '在线' : '重连中' },
  { key: 'nav', label: 'FPGA 导航', tone: linkTone(platform.value?.nav_link), value: linkLabel(platform.value?.nav_link) },
  { key: 'ctl', label: 'FPGA 控制', tone: linkTone(platform.value?.control_link), value: linkLabel(platform.value?.control_link) },
  {
    key: 'vision', label: '视觉',
    tone: props.yt.state.value?.detection_status ? 'ok' : 'muted',
    value: props.yt.state.value?.detection_status ? '运行' : '未接入',
  },
])

function onEstop() {
  void props.yt.estop(!estopActive.value)
}

function saveToken() {
  props.yt.saveToken(tokenDraft.value)
  tokenOpen.value = false
}
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <svg class="logo" viewBox="0 0 48 48" aria-hidden="true">
        <defs>
          <linearGradient id="yt-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#2fe0c4" /><stop offset="1" stop-color="#3aa8ff" />
          </linearGradient>
        </defs>
        <path d="M6 32 L16 20 L23 27 L31 14 L42 32" fill="none" stroke="url(#yt-g)" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round" />
        <circle cx="15" cy="37" r="4" fill="none" stroke="#2fe0c4" stroke-width="2.6" />
        <circle cx="33" cy="37" r="4" fill="none" stroke="#3aa8ff" stroke-width="2.6" />
        <path d="M15 37 L24 31 L33 37" fill="none" stroke="#9fb1bd" stroke-width="2" stroke-linecap="round" />
      </svg>
      <div>
        <h1>云拓 <span>YunTuo</span></h1>
        <p>多模态复杂地形轮腿机器人 · 嵌入式芯片与系统设计竞赛 FPGA 创新设计赛道</p>
      </div>
    </div>

    <div class="status-row" aria-label="链路状态">
      <span v-for="l in links" :key="l.key" class="pill" :class="`tone-${l.tone}`">{{ l.label }} {{ l.value }}</span>
    </div>

    <div class="controls">
      <div class="mode-switch" role="group" aria-label="系统模式">
        <button type="button" :class="{ on: yt.isMock.value }" :disabled="yt.busy.mode" @click="yt.switchMode('mock')">模拟</button>
        <button type="button" :class="{ on: !yt.isMock.value }" :disabled="yt.busy.mode" @click="yt.switchMode('real')">实车</button>
      </div>
      <button type="button" class="btn ghost token-btn" :title="yt.token.value ? '已设置访问 Token' : '设置访问 Token（公网写接口需要）'"
        @click="tokenOpen = !tokenOpen">
        {{ yt.token.value ? '已授权' : '访问 Token' }}
      </button>
      <span class="clock num">{{ now.toLocaleTimeString('zh-CN', { hour12: false }) }}</span>
      <button type="button" class="estop" :class="{ active: estopActive }" :disabled="yt.busy.estop" @click="onEstop">
        <strong>{{ estopActive ? '解除急停' : '急停' }}</strong>
        <small>{{ estopActive ? 'ESTOP ACTIVE' : 'EMERGENCY STOP' }}</small>
      </button>
    </div>

    <div v-if="tokenOpen" class="token-pop panel">
      <label for="token-input">公网访问 Token（仅保存在本浏览器）</label>
      <div class="token-row">
        <input id="token-input" v-model="tokenDraft" class="field" type="password" autocomplete="off" placeholder="Bearer Token" />
        <button type="button" class="btn primary" @click="saveToken">保存</button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  position: relative;
  display: grid;
  grid-template-columns: minmax(280px, auto) 1fr auto;
  align-items: center;
  gap: 18px;
  padding: 14px 22px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(10, 18, 26, 0.95), rgba(10, 18, 26, 0.75));
  position: sticky;
  top: 0;
  z-index: 20;
  backdrop-filter: blur(10px);
}
.brand { display: flex; align-items: center; gap: 14px; min-width: 0; }
.logo { width: 44px; height: 44px; flex: none; }
h1 { margin: 0; font-size: 22px; letter-spacing: 0.08em; font-weight: 700; }
h1 span { font-size: 13px; letter-spacing: 0.18em; color: var(--accent); font-weight: 600; margin-left: 6px; }
.brand p { margin: 2px 0 0; color: var(--text-3); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.status-row { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.controls { display: flex; align-items: center; gap: 10px; }
.mode-switch { display: inline-flex; padding: 3px; border-radius: 10px; border: 1px solid var(--line-strong); background: rgba(0, 0, 0, 0.3); }
.mode-switch button { border: 0; background: transparent; padding: 6px 12px; border-radius: 7px; color: var(--text-2); font-size: 13px; font-weight: 600; }
.mode-switch button.on { background: var(--accent-dim); color: var(--accent); }
.token-btn { min-height: 34px; padding: 0 10px; font-size: 12px; }
.clock { color: var(--text-2); font-size: 13px; min-width: 64px; text-align: right; }
.estop {
  display: grid;
  place-items: center;
  min-width: 112px;
  height: 48px;
  border-radius: 12px;
  border: 2px solid #ff4d5e;
  background: radial-gradient(circle at 50% 30%, #ff5d6c, #b3121f);
  color: #fff;
  box-shadow: 0 0 0 4px rgba(255, 77, 94, 0.15), 0 8px 20px rgba(179, 18, 31, 0.4);
}
.estop strong { font-size: 16px; letter-spacing: 0.2em; line-height: 1; }
.estop small { font-size: 9px; letter-spacing: 0.16em; opacity: 0.85; }
.estop.active { background: repeating-linear-gradient(45deg, #ffb547 0 10px, #1a1a1a 10px 20px); border-color: #ffb547; color: #fff; animation: pulse 1.2s infinite; }
.estop.active strong { text-shadow: 0 1px 2px #000; }
@keyframes pulse { 50% { box-shadow: 0 0 0 8px rgba(255, 181, 71, 0.25); } }
.token-pop { position: absolute; right: 22px; top: 70px; width: 340px; padding: 14px; z-index: 30; }
.token-pop label { display: block; font-size: 12px; color: var(--text-2); margin-bottom: 8px; }
.token-row { display: flex; gap: 8px; }
@media (max-width: 1180px) {
  .topbar { grid-template-columns: 1fr auto; }
  .status-row { grid-column: 1 / -1; justify-content: flex-start; order: 3; }
}
@media (max-width: 640px) {
  .topbar { padding: 12px; gap: 10px; }
  .brand p, h1 span { display: none; }
  h1 { white-space: nowrap; }
  .logo { width: 36px; height: 36px; }
  .clock, .token-btn { display: none; }
  .estop { min-width: 88px; height: 44px; }
}
</style>
