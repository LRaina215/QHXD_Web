<script setup lang="ts">
import { computed, ref } from 'vue'
import { AudioLines, Mic, Radio, Send, Sparkles } from 'lucide-vue-next'
import BrandMark from './BrandMark.vue'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const text = ref('')
const duration = ref(4)
const examples = ['找到红色水瓶并移动到它旁边', '跟着我', '去 B 点', '开始巡检', '你是谁']
const reply = computed(() => props.yt.smart.value)
const busy = computed(() => props.yt.busy.voice)

function send(value = text.value) {
  if (!value.trim() || busy.value) return
  void props.yt.sendText(value)
  text.value = ''
}
</script>

<template>
  <section class="card voice">
    <div class="card-head">
      <h2 class="card-title"><Sparkles :size="17" />语音助手</h2>
      <span class="spacer"></span>
      <span class="tag" :class="busy ? 'run' : 'off'"><i class="dot"></i>{{ yt.voiceStatus.value }}</span>
    </div>
    <div class="card-body">
      <div class="chat" aria-live="polite">
        <template v-if="reply">
          <p class="me">{{ reply.recognized_text || '…' }}</p>
          <div class="bot-row">
            <BrandMark :size="30" :rounded="15" />
            <div class="bot">
              <p>{{ reply.reply_text || reply.error_reason }}</p>
              <span class="meta num">{{ reply.intent ?? 'unknown' }} · {{ reply.parser }}{{ reply.llm_model ? ` · ${reply.llm_model}` : '' }} · {{ reply.confidence.toFixed(2) }}</span>
            </div>
          </div>
        </template>
        <div v-else class="hello">
          <div class="hello-head"><BrandMark :size="30" :rounded="15" /><AudioLines :size="20" /></div>
          <p>直接说出任务，运动类命令会先请你确认。</p>
          <div class="ex">
            <button v-for="e in examples" :key="e" type="button" @click="send(e)">{{ e }}</button>
          </div>
        </div>
      </div>
      <form class="say" @submit.prevent="send()">
        <label class="sr-only" for="say">文字命令</label>
        <input id="say" v-model="text" class="field" type="text" placeholder="输入命令，例如：找到红色水瓶" autocomplete="off" />
        <button type="submit" class="send" :disabled="busy || !text.trim()" aria-label="发送"><Send :size="18" /></button>
      </form>
      <div class="mics">
        <button type="button" class="btn sm quiet" :disabled="busy" @click="yt.recordBrowser(duration)"><Mic :size="16" />网页麦克风</button>
        <button type="button" class="btn sm quiet" :disabled="busy" @click="yt.recordOnboard(duration)"><Radio :size="16" />车载麦克风</button>
        <label class="dur">
          <span class="sr-only">录音时长</span>
          <select v-model.number="duration" class="field">
            <option :value="3">3 秒</option><option :value="4">4 秒</option><option :value="6">6 秒</option>
          </select>
        </label>
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat { min-height: 132px; display: flex; flex-direction: column; gap: 10px; margin-bottom: 14px; }
.me { align-self: flex-end; max-width: 85%; margin: 0; padding: 10px 14px; border-radius: 16px 16px 4px 16px; background: var(--ink); color: #fff; font-size: 14px; }
.bot-row { display: flex; align-items: flex-end; gap: 8px; max-width: 96%; }
.bot { min-width: 0; padding: 10px 14px; border-radius: 16px 16px 16px 4px; background: var(--surface-2); }
.hello-head { display: flex; align-items: center; gap: 10px; }
.bot p { margin: 0; font-size: 14px; line-height: 1.55; }
.meta { display: block; margin-top: 6px; font-size: 11px; color: var(--ink-3); }
.hello { display: grid; justify-items: start; gap: 8px; padding: 14px; border-radius: 14px; background: var(--surface-2); color: var(--ink-3); }
.hello p { margin: 0; color: var(--ink-2); font-size: 13px; }
.ex { display: flex; flex-wrap: wrap; gap: 6px; }
.ex button { height: 30px; padding: 0 12px; border-radius: 999px; border: 1px solid var(--line-2); background: var(--surface); color: var(--ink); font-size: 12px; font-weight: 550; }
.ex button:hover { border-color: var(--brand); color: var(--brand); }
.say { position: relative; }
.say .field { padding-right: 52px; height: 48px; border-radius: 14px; }
.send { position: absolute; right: 6px; top: 6px; width: 36px; height: 36px; display: grid; place-items: center; border: 0; border-radius: 10px; background: var(--brand); color: #fff; }
.send:disabled { background: var(--surface-3); color: var(--ink-3); }
.mics { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; align-items: center; }
.dur { margin-left: auto; }
.dur .field { height: 34px; width: 86px; padding: 0 10px; border-radius: 10px; font-size: 13px; }
</style>
