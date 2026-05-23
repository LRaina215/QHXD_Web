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
  background: rgba(3, 8, 13, 0.68);
}

.voice-confirm-dialog {
  width: min(620px, 100%);
  max-height: min(760px, calc(100vh - 40px));
  overflow: auto;
  padding: 22px;
  border: 1px solid rgba(124, 194, 255, 0.28);
  border-radius: 8px;
  background: #0e1823;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.42);
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
  color: #7cc2ff;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.voice-confirm-header h2 {
  margin: 0;
  color: #f5f7fa;
  font-size: 1.25rem;
}

.icon-button {
  width: 36px;
  height: 36px;
  padding: 0;
  border-radius: 8px;
  background: #23384f;
  font-size: 1.25rem;
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
  color: #fde68a;
  background: rgba(180, 83, 9, 0.16);
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.voice-confirm-error {
  color: #fecaca;
  background: rgba(127, 29, 29, 0.24);
  border: 1px solid rgba(248, 113, 113, 0.3);
}

.voice-confirm-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.voice-confirm-item {
  min-width: 0;
  padding: 12px;
  border: 1px solid rgba(115, 147, 179, 0.22);
  border-radius: 8px;
  background: rgba(18, 31, 44, 0.96);
}

.voice-confirm-item.wide {
  grid-column: 1 / -1;
}

.voice-confirm-item span {
  display: block;
  margin-bottom: 6px;
  color: #8ea1b5;
  font-size: 0.84rem;
}

.voice-confirm-item strong {
  color: #f5f7fa;
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
  background: #23384f;
}

.confirm-button {
  background: #b45309;
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
