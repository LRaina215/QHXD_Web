<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { TASK_TYPE_LABELS, targetLabel } from '../labels'
import type { PendingCommand } from '../types'

const props = defineProps<{ result: PendingCommand; loading: boolean; error?: string }>()
const emit = defineEmits<{ confirm: []; cancel: []; close: [] }>()
const confirmButton = ref<HTMLButtonElement | null>(null)

const command = computed(() => props.result.command ?? props.result.intent ?? '')
const targetText = computed(() => {
  const p = props.result.payload ?? {}
  if (p.target_class) return String(p.label || targetLabel(String(p.target_class), p.color ? String(p.color) : null))
  const wp = props.result.waypoint_id ?? p.waypoint_id
  if (wp) return String(wp)
  if (command.value === 'return_home') return '起点'
  if (command.value === 'start_patrol') return String(p.patrol_id ?? '默认巡检路线')
  return '--'
})
const parser = computed(() => [props.result.parser, props.result.llm_model].filter(Boolean).join(' / ') || '--')

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && !props.loading) emit('close')
}
onMounted(() => {
  window.addEventListener('keydown', onKey)
  confirmButton.value?.focus()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="backdrop" role="presentation" @click.self="!loading && emit('close')">
    <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <header>
        <p class="kicker">运动任务确认</p>
        <h2 id="confirm-title">{{ TASK_TYPE_LABELS[command] ?? command }}：{{ targetText }}</h2>
      </header>
      <p class="note">确认后任务交给 FPGA 导航执行，速度由 FPGA 安全限幅；随时可按右上角急停。</p>
      <dl>
        <div class="wide"><dt>识别文本</dt><dd>{{ result.recognized_text || '--' }}</dd></div>
        <div><dt>命令</dt><dd class="num">{{ command || '--' }}</dd></div>
        <div><dt>置信度</dt><dd class="num">{{ result.confidence != null ? result.confidence.toFixed(2) : '--' }}</dd></div>
        <div class="wide"><dt>解析方式</dt><dd>{{ parser }}</dd></div>
        <div class="wide"><dt>说明</dt><dd>{{ result.detail || '--' }}</dd></div>
      </dl>
      <p v-if="error" class="err">{{ error }}</p>
      <footer>
        <button type="button" class="btn ghost" :disabled="loading" @click="emit('cancel')">取消任务</button>
        <button ref="confirmButton" type="button" class="btn primary" :disabled="loading" @click="emit('confirm')">
          {{ loading ? '处理中…' : '确认执行' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 20px; background: rgba(2, 5, 8, 0.7); backdrop-filter: blur(6px); }
.dialog { width: min(560px, 100%); padding: 22px; border-radius: 16px; background: var(--panel-solid); border: 1px solid var(--line-strong); border-top: 4px solid var(--warn); box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5); }
.kicker { margin: 0 0 4px; color: var(--warn); font-size: 12px; letter-spacing: 0.12em; }
h2 { margin: 0; font-size: 20px; }
.note { margin: 12px 0; padding: 10px 12px; border-radius: 10px; font-size: 13px; color: var(--text-2); background: rgba(255, 181, 71, 0.08); border: 1px solid rgba(255, 181, 71, 0.25); }
dl { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 0; }
dl > div { padding: 8px 10px; border-radius: 9px; border: 1px solid var(--line); background: rgba(255, 255, 255, 0.02); min-width: 0; }
.wide { grid-column: 1 / -1; }
dt { font-size: 11px; color: var(--text-3); margin-bottom: 3px; }
dd { margin: 0; font-size: 14px; overflow-wrap: anywhere; }
.err { color: var(--danger); font-size: 13px; }
footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
footer .btn { min-height: 42px; min-width: 110px; }
@media (max-width: 560px) {
  .backdrop { place-items: end center; padding: 10px; }
  dl { grid-template-columns: 1fr; }
  footer .btn { flex: 1; }
}
</style>
