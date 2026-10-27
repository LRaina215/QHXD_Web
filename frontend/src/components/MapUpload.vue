<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { CheckCircle2, FileUp, Upload, X } from 'lucide-vue-next'
import type { YunTuo } from '../composables/useYunTuo'

const props = defineProps<{ yt: YunTuo }>()
const open = ref(false)
const file = ref<File | null>(null)
const fileError = ref('')
const trigger = ref<HTMLButtonElement | null>(null)
const dialog = ref<HTMLElement | null>(null)
const status = computed(() => props.yt.mapUpload.value)
const sending = computed(() => props.yt.busy.map || props.yt.mapUploading.value)
const taskActive = computed(() => ['pending', 'running', 'paused'].includes(props.yt.state.value?.task_status.state ?? ''))
const unavailable = computed(() => {
  if (props.yt.isMock.value) return '请先连接真实机器人。'
  if (props.yt.platform.value?.nav_link !== 'online') return 'FPGA未在线，连接后才能下发地图。'
  if (props.yt.platform.value?.fpga_mode !== 'idle') return '请先让机器人进入空闲；上传不会自动解除运行急停。'
  if (taskActive.value) return '请先取消当前任务，再更换地图。'
  return ''
})
const labels: Record<string, string> = { idle: '等待选择', queued: '等待下发', uploading: '正在下发', ready: '地图已加载',
  failed: '上传失败', cancelled: '上传已中止', invalidated: '地图已失效', unavailable: '暂不可用' }
const errorState = computed(() => ['failed', 'cancelled', 'invalidated', 'unavailable'].includes(status.value.state))

function choose(event: Event) {
  props.yt.mapUploadError.value = ''
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  fileError.value = file.value && (!file.value.name.toLowerCase().endsWith('.nvmp') || file.value.size < 48 || file.value.size > 86064)
    ? '请选择48至86064字节的 .nvmp 地图包，图片或点云需要先转换。' : ''
}
function close() {
  open.value = false
  window.removeEventListener('keydown', keydown)
  trigger.value?.focus()
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
  if (event.key === 'Tab' && dialog.value) {
    const nodes = dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)')
    const first = nodes[0], last = nodes[nodes.length - 1]
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) {
      event.preventDefault(); last?.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first?.focus()
    }
  }
}
async function show() {
  open.value = true
  window.addEventListener('keydown', keydown)
  await nextTick()
  dialog.value?.focus()
}
async function preview() { if (file.value && await props.yt.previewMap(file.value)) close() }
onBeforeUnmount(() => window.removeEventListener('keydown', keydown))
</script>

<template>
  <button ref="trigger" class="upload-entry" type="button" @click="show"><Upload :size="15" />上传地图</button>
  <Teleport to="body">
    <div v-if="open" class="map-backdrop" @click.self="close">
      <section ref="dialog" class="map-dialog" role="dialog" aria-modal="true" aria-labelledby="map-upload-title" tabindex="-1">
        <header><div><p class="eyebrow">场地地图</p><h2 id="map-upload-title">上传先验地图</h2></div>
          <button class="close" type="button" aria-label="关闭地图上传" @click="close"><X :size="20" /></button></header>
        <p class="intro">选择已转换好的地图包，下发到FPGA后更新场地视图。</p>
        <label class="file-picker" :class="{ disabled: sending }">
          <FileUp :size="30" /><strong>{{ file?.name || '选择 .nvmp 文件' }}</strong>
          <span>{{ file ? `${(file.size / 1024).toFixed(1)} KB` : 'SLF128地图包 · 最大84 KB' }}</span>
          <input type="file" accept=".nvmp" :disabled="sending" aria-label="选择地图文件" @change="choose" />
        </label>
        <p v-if="fileError || yt.mapUploadError.value" class="error" role="alert">{{ fileError || yt.mapUploadError.value }}</p>
        <div class="map-status" :class="{ error: errorState, success: status.state === 'ready' }" role="status" aria-live="polite">
          <strong><CheckCircle2 v-if="status.state === 'ready'" :size="17" />{{ labels[status.state] || status.state }}</strong>
          <span v-if="status.filename">{{ status.filename }}</span>
          <progress v-if="yt.mapUploading.value || status.state === 'ready'" :value="status.progress || 0" max="100" aria-label="地图下发进度" />
          <span v-if="yt.mapUploading.value">{{ status.progress || 0 }}% · {{ status.sent_bytes || 0 }} / {{ status.total_bytes || 0 }} 字节已确认</span>
          <p>{{ status.detail }}</p>
          <p v-if="status.state === 'ready'">地图已加载不代表定位完成。请设置初始位姿并完成对准后，再下发导航任务。</p>
        </div>
        <p v-if="unavailable" class="hint">{{ unavailable }}</p>
        <p class="note">地图会保存在机器人上；FPGA复位后需重新下发。关闭此窗口不会中断上传。</p>
        <footer><button class="btn" type="button" @click="close">关闭</button>
          <button class="btn" type="button" :disabled="!file || !!fileError || sending" @click="preview">仅预览</button>
          <button class="btn primary" type="button" :disabled="!file || !!fileError || !!unavailable || sending"
            @click="file && yt.uploadMap(file)"><Upload :size="17" />{{ sending ? '下发中…' : '上传并下发' }}</button></footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.upload-entry { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--stage-line); border-radius: 8px; background: rgba(255,255,255,.06); color: var(--stage-ink); padding: 7px 10px; font-size: 12px; white-space: nowrap; }
.upload-entry:hover { background: rgba(255,255,255,.13); }
.map-backdrop { position: fixed; inset: 0; z-index: 70; background: rgba(15,18,22,.55); display: grid; place-items: center; padding: 20px; }
.map-dialog { width: min(100%,520px); max-height: calc(100dvh - 40px); overflow: auto; border-radius: 20px; padding: 26px; background: var(--surface); color: var(--ink); box-shadow: 0 24px 80px rgba(0,0,0,.25); }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
header p, h2 { margin: 0; } h2 { margin-top: 5px; font-size: 22px; }
.close { border: 0; background: none; color: var(--ink-2); padding: 6px; }
.intro, .note, .hint { font-size: 13px; line-height: 1.6; color: var(--ink-2); }
.file-picker { position: relative; display: flex; flex-direction: column; align-items: center; gap: 9px; border: 1px dashed var(--line-2); background: var(--surface-2); border-radius: 12px; padding: 24px 16px; margin: 18px 0; cursor: pointer; }
.file-picker strong { max-width: 100%; overflow-wrap: anywhere; font-size: 14px; } .file-picker span { font-size: 12px; color: var(--ink-3); }
.file-picker svg { color: var(--brand); } .file-picker input { position: absolute; inset: 0; opacity: 0; width: 100%; height: 100%; cursor: pointer; }
.file-picker:focus-within { outline: 2px solid var(--brand); outline-offset: 3px; } .disabled { opacity: .55; }
.map-status { border-radius: 12px; background: var(--surface-2); padding: 14px; font-size: 13px; line-height: 1.6; }
.map-status strong { display: flex; align-items: center; gap: 6px; } .map-status p { margin: 5px 0 0; overflow-wrap: anywhere; }
.map-status span { font-size: 12px; } .map-status progress { display: block; width: 100%; height: 8px; margin: 12px 0 6px; accent-color: var(--brand); }
.success { background: var(--ok-soft); color: var(--ok); } .error { color: var(--bad); }
.note { font-size: 12px; color: var(--ink-3); } footer { justify-content: flex-end; margin-top: 20px; }
@media(max-width:560px) { .map-backdrop { padding: 12px; } .map-dialog { padding: 20px; } .upload-entry { padding: 7px 8px; } }
</style>
