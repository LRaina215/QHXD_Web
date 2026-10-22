<script setup lang="ts">
import { computed, ref } from 'vue'
import { ENABLE_LOCAL_RECORD_COMMAND } from '../config/api'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const text = ref('找到红色水瓶并移动到它旁边')
const duration = ref(4)
const examples = ['找到红色水瓶并移动到它旁边', '跟着我', '去 A 点', '开始巡检', '暂停', '你是谁']
const reply = computed(() => props.yt.smart.value)

function send() {
  void props.yt.sendText(text.value)
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h2 class="panel-title">语音交互 <small>ASR · LLM · TTS</small></h2>
      <span class="pill" :class="yt.busy.voice ? 'tone-info' : 'tone-muted'">{{ yt.voiceStatus.value }}</span>
    </div>
    <div class="panel-body">
      <form class="say" @submit.prevent="send">
        <label class="sr-only" for="say-input">文本命令</label>
        <input id="say-input" v-model="text" class="field" type="text" placeholder="输入命令，例如：找到红色水瓶" />
        <button type="submit" class="btn primary" :disabled="yt.busy.voice || !text.trim()">发送</button>
      </form>
      <div class="examples">
        <button v-for="e in examples" :key="e" type="button" class="ex" @click="text = e">{{ e }}</button>
      </div>
      <div class="mic-row">
        <button type="button" class="btn" :disabled="yt.busy.voice" @click="yt.recordBrowser(duration)">网页麦克风</button>
        <button type="button" class="btn" :disabled="yt.busy.voice" @click="yt.recordOnboard(duration)">车载麦克风</button>
        <label class="dur">
          <span>时长</span>
          <select v-model.number="duration" class="field">
            <option :value="3">3 s</option><option :value="4">4 s</option><option :value="6">6 s</option>
          </select>
        </label>
      </div>
      <div v-if="reply" class="reply">
        <p class="heard"><span>听到</span>{{ reply.recognized_text || '--' }}</p>
        <p class="answer">{{ reply.reply_text || reply.error_reason }}</p>
        <p class="meta num">{{ reply.intent ?? 'unknown' }} · {{ reply.parser }}{{ reply.llm_model ? ` · ${reply.llm_model}` : '' }} · {{ reply.confidence.toFixed(2) }}</p>
      </div>
      <p v-if="!ENABLE_LOCAL_RECORD_COMMAND" class="hint">运动类命令都会弹出确认框，确认后才交给 FPGA 执行。</p>
    </div>
  </section>
</template>

<style scoped>
.say { display: flex; gap: 8px; }
.say .field { flex: 1; min-width: 0; }
.examples { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.ex { border: 1px dashed var(--line-strong); background: transparent; color: var(--text-2); font-size: 12px; padding: 4px 9px; border-radius: 999px; }
.ex:hover { color: var(--accent); border-color: var(--accent); }
.mic-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.dur { display: flex; align-items: center; gap: 6px; margin-left: auto; font-size: 12px; color: var(--text-3); }
.dur .field { width: 74px; }
.reply { margin-top: 12px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line); background: rgba(58, 168, 255, 0.05); }
.reply p { margin: 0; }
.heard { font-size: 12px; color: var(--text-2); }
.heard span { color: var(--text-3); margin-right: 8px; }
.answer { margin-top: 6px !important; font-size: 14px; line-height: 1.5; }
.meta { margin-top: 6px !important; font-size: 11px; color: var(--text-3); }
.hint { margin: 10px 0 0; font-size: 12px; color: var(--text-3); }
</style>
