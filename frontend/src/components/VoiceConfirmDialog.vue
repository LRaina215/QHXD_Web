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
  background:
    linear-gradient(135deg, rgba(21, 19, 15, 0.72), rgba(21, 19, 15, 0.42)),
    rgba(21, 19, 15, 0.54);
  backdrop-filter: blur(9px);
}

.voice-confirm-dialog {
  width: min(680px, 100%);
  max-height: min(800px, calc(100vh - 40px));
  overflow: auto;
  padding: 22px;
  border: 1px solid #15130f;
  border-left: 8px solid #f3ad44;
  border-radius: 8px;
  background: #fffaf0;
  box-shadow: 0 34px 100px rgba(21, 19, 15, 0.38);
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
  color: #d98218;
  font-family: "DIN Alternate", "Avenir Next", sans-serif;
  font-size: 0.75rem;
  font-weight: 900;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.voice-confirm-header h2 {
  margin: 0;
  color: #15130f;
  font-family: "DIN Alternate", "Avenir Next", "Microsoft YaHei", sans-serif;
  font-size: 1.34rem;
  font-weight: 900;
}

.icon-button {
  width: 38px;
  height: 38px;
  padding: 0;
  border-radius: 8px;
  border: 1px solid #b8aa97;
  background: #fffaf0;
  color: #51483d;
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
  color: #15130f;
  background: #fff2d9;
  border: 1px solid rgba(217, 130, 24, 0.34);
}

.voice-confirm-error {
  color: #a62b22;
  background: #fff0ec;
  border: 1px solid rgba(196, 56, 43, 0.3);
}

.voice-confirm-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.voice-confirm-item {
  min-width: 0;
  padding: 12px;
  border: 1px solid #e0d4c4;
  border-radius: 8px;
  background: rgba(255, 253, 248, 0.72);
}

.voice-confirm-item.wide {
  grid-column: 1 / -1;
}

.voice-confirm-item span {
  display: block;
  margin-bottom: 6px;
  color: #726a5f;
  font-size: 0.82rem;
  font-weight: 800;
}

.voice-confirm-item strong {
  color: #15130f;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.voice-confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 18px;
}

.cancel-button,
.confirm-button {
  min-height: 44px;
  border-radius: 8px;
  font-weight: 900;
}

.cancel-button {
  color: #15130f;
  border: 1px solid #b8aa97;
  background: #fffaf0;
  box-shadow: none;
}

.confirm-button {
  color: #15130f;
  border: 1px solid #f3ad44;
  background: #f3ad44;
}

@media (max-width: 560px) {
  .voice-confirm-grid {
    grid-template-columns: 1fr;
  }

  .voice-confirm-actions {
    flex-direction: column-reverse;
  }

  .cancel-button,
  .confirm-button {
    width: 100%;
  }
}
</style>
