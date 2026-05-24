<script setup lang="ts">
import { computed } from 'vue'

type VoiceConfirmResult = {
  recognized_text?: string
  intent?: string | null
  command?: string | null
  waypoint_id?: string | null
  payload?: Record<string, string | number | boolean | null>
  confidence?: number
  parser?: string
  llm_backend?: string | null
  llm_model?: string | null
  detail?: string
  pending_command_id?: string | null
}

const props = defineProps<{
  result: VoiceConfirmResult
  loading: boolean
  error?: string
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
  close: []
}>()

const waypointLabel = computed(() => {
  const waypoint = props.result.waypoint_id ?? props.result.payload?.waypoint_id
  return waypoint === null || waypoint === undefined ? '--' : String(waypoint)
})

const confidenceLabel = computed(() => {
  if (props.result.confidence === null || props.result.confidence === undefined) {
    return '--'
  }
  return props.result.confidence.toFixed(2)
})

const parserLabel = computed(() => {
  const parts = [props.result.parser, props.result.llm_backend, props.result.llm_model]
    .filter((value): value is string => Boolean(value))
  return parts.length > 0 ? parts.join(' / ') : '--'
})
</script>

<template>
  <div class="voice-confirm-backdrop" role="presentation">
    <section class="voice-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="voice-confirm-title">
      <header class="voice-confirm-header">
        <div>
          <p class="voice-confirm-kicker">Voice confirmation</p>
          <h2 id="voice-confirm-title">移动任务确认</h2>
        </div>
        <button class="icon-button" type="button" :disabled="loading" aria-label="关闭确认弹窗" @click="emit('close')">
          ×
        </button>
      </header>

      <p class="risk-note">该操作将使机器人移动或改变任务流，请确认解析结果无误后再执行。</p>

      <div class="voice-confirm-grid">
        <div class="voice-confirm-item wide">
          <span>识别文本</span>
          <strong>{{ result.recognized_text || '--' }}</strong>
        </div>
        <div class="voice-confirm-item">
          <span>解析意图</span>
          <strong>{{ result.intent ?? '--' }}</strong>
        </div>
        <div class="voice-confirm-item">
          <span>执行命令</span>
          <strong>{{ result.command ?? '--' }}</strong>
        </div>
        <div class="voice-confirm-item">
          <span>目标点</span>
          <strong>{{ waypointLabel }}</strong>
        </div>
        <div class="voice-confirm-item">
          <span>置信度</span>
          <strong>{{ confidenceLabel }}</strong>
        </div>
        <div class="voice-confirm-item wide">
          <span>解析方式</span>
          <strong>{{ parserLabel }}</strong>
        </div>
        <div class="voice-confirm-item wide">
          <span>详情</span>
          <strong>{{ result.detail || '--' }}</strong>
        </div>
      </div>

      <p v-if="error" class="voice-confirm-error">{{ error }}</p>

      <footer class="voice-confirm-actions">
        <button class="cancel-button" type="button" :disabled="loading" @click="emit('cancel')">
          {{ loading ? '处理中...' : '取消任务' }}
        </button>
        <button class="confirm-button" type="button" :disabled="loading" @click="emit('confirm')">
          {{ loading ? '确认中...' : '确认执行' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.voice-confirm-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(15, 23, 42, 0.36);
  backdrop-filter: blur(6px);
}

.voice-confirm-dialog {
  width: min(640px, 100%);
  max-height: min(760px, calc(100vh - 40px));
  overflow: auto;
  padding: 22px;
  border: 1px solid #dbe5f2;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 28px 80px rgba(15, 23, 42, 0.22);
}

.voice-confirm-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.voice-confirm-kicker {
  margin: 0 0 6px;
  color: #2563eb;
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.voice-confirm-header h2 {
  margin: 0;
  color: #0f172a;
  font-size: 1.18rem;
}

.icon-button {
  width: 34px;
  height: 34px;
  padding: 0;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #475569;
  box-shadow: none;
  font-size: 1.2rem;
  line-height: 1;
}

.risk-note,
.voice-confirm-error {
  margin: 0 0 14px;
  padding: 12px 14px;
  border-radius: 8px;
  line-height: 1.5;
}

.risk-note {
  color: #a16207;
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.voice-confirm-error {
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
}

.voice-confirm-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.voice-confirm-item {
  min-width: 0;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.voice-confirm-item.wide {
  grid-column: 1 / -1;
}

.voice-confirm-item span {
  display: block;
  margin-bottom: 6px;
  color: #64748b;
  font-size: 0.82rem;
}

.voice-confirm-item strong {
  color: #0f172a;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.voice-confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 18px;
}

.cancel-button {
  color: #1e293b;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  box-shadow: none;
}

.confirm-button {
  background: #2563eb;
}

@media (max-width: 560px) {
  .voice-confirm-grid {
    grid-template-columns: 1fr;
  }

  .voice-confirm-actions {
    flex-direction: column-reverse;
  }
}
</style>
