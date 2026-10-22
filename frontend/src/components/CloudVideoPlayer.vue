<script setup lang="ts">
import type HlsType from 'hls.js'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiUrl } from '../config/api'

type VideoSessionResponse = {
  success: boolean
  data?: {
    webrtc_url: string
    hls_url: string
    expires_in: number
  }
}

const props = defineProps<{
  apiToken: string
  fallbackUrl: string
  fallbackAvailable: boolean
}>()

const emit = defineEmits<{
  modeChange: [mode: string]
}>()

const videoElement = ref<HTMLVideoElement | null>(null)
const mode = ref<'connecting' | 'webrtc' | 'hls' | 'mjpeg' | 'offline'>('connecting')
const detail = ref('正在建立低延迟视频链路')
const fallbackImageFailed = ref(false)
const fallbackReload = ref(0)
let peerConnection: RTCPeerConnection | null = null
let hls: HlsType | null = null
let whepSessionUrl = ''
let fallbackTimer: number | null = null
let retryTimer: number | null = null
let fallbackReloadTimer: number | null = null
let connectionGeneration = 0
// 云端没有推流时不要每 5 秒重试一次：5 s 起步，翻倍到 60 s，连上后复位
const RETRY_MIN_MS = 5000
const RETRY_MAX_MS = 60000
let retryDelayMs = RETRY_MIN_MS

const modeLabel = computed(() => ({
  connecting: 'CONNECTING',
  webrtc: 'WEBRTC',
  hls: 'HLS FALLBACK',
  mjpeg: 'MJPEG FALLBACK',
  offline: 'OFFLINE',
})[mode.value])

// 低延迟链路连上之前（包括后台重试期间）一直显示检测画面，重连时不黑屏
const showFallbackImage = computed(() => (
  (mode.value === 'mjpeg' || mode.value === 'connecting')
  && props.fallbackAvailable && !!props.fallbackUrl && !fallbackImageFailed.value
))

const fallbackSrc = computed(() => {
  if (!fallbackReload.value) {
    return props.fallbackUrl
  }
  return `${props.fallbackUrl}${props.fallbackUrl.includes('?') ? '&' : '?'}r=${fallbackReload.value}`
})

function setMode(nextMode: typeof mode.value, nextDetail: string) {
  if (nextMode === 'webrtc' || nextMode === 'hls') {
    retryDelayMs = RETRY_MIN_MS
  }
  mode.value = nextMode
  detail.value = nextDetail
  emit('modeChange', nextMode)
}

// 已经在显示检测画面时，重连在后台进行，界面保持 MJPEG 状态
function setConnecting(nextDetail: string) {
  if (mode.value !== 'mjpeg') {
    setMode('connecting', nextDetail)
  }
}

async function createVideoSession() {
  const response = await fetch(apiUrl('/api/video/session'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${props.apiToken.trim()}`,
    },
    credentials: 'include',
  })
  if (!response.ok) {
    throw new Error(`video session HTTP ${response.status}`)
  }
  const payload = await response.json() as VideoSessionResponse
  if (!payload.success || !payload.data?.webrtc_url || !payload.data.hls_url) {
    throw new Error('video session payload is incomplete')
  }
  return payload.data
}

async function waitForIceGathering(pc: RTCPeerConnection) {
  if (pc.iceGatheringState === 'complete') {
    return
  }
  await new Promise<void>((resolve) => {
    const timeout = window.setTimeout(resolve, 3000)
    const listener = () => {
      if (pc.iceGatheringState !== 'complete') {
        return
      }
      window.clearTimeout(timeout)
      pc.removeEventListener('icegatheringstatechange', listener)
      resolve()
    }
    pc.addEventListener('icegatheringstatechange', listener)
  })
}

async function startWebRtc(url: string, generation: number) {
  const video = videoElement.value
  if (!video) {
    throw new Error('video element is unavailable')
  }
  const pc = new RTCPeerConnection()
  peerConnection = pc
  pc.addTransceiver('video', { direction: 'recvonly' })
  pc.ontrack = (event) => {
    if (generation !== connectionGeneration) {
      return
    }
    video.srcObject = event.streams[0] ?? new MediaStream([event.track])
    void video.play().catch(() => undefined)
  }
  pc.onconnectionstatechange = () => {
    if (generation !== connectionGeneration) {
      return
    }
    if (pc.connectionState === 'connected') {
      clearFallbackTimer()
      setMode('webrtc', '云端低延迟视频已连接')
    } else if (['failed', 'disconnected', 'closed'].includes(pc.connectionState)) {
      void startHlsFallback(generation)
    }
  }

  const offer = await pc.createOffer()
  await pc.setLocalDescription(offer)
  await waitForIceGathering(pc)
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/sdp' },
    body: pc.localDescription?.sdp ?? offer.sdp,
    credentials: 'include',
  })
  if (!response.ok) {
    throw new Error(`WHEP HTTP ${response.status}`)
  }
  const location = response.headers.get('Location')
  whepSessionUrl = location ? new URL(location, window.location.href).toString() : ''
  await pc.setRemoteDescription({ type: 'answer', sdp: await response.text() })
  fallbackTimer = window.setTimeout(() => {
    if (generation === connectionGeneration && mode.value !== 'webrtc') {
      void startHlsFallback(generation)
    }
  }, 8000)
}

async function startHlsFallback(generation: number) {
  if (generation !== connectionGeneration || !currentHlsUrl) {
    return
  }
  clearFallbackTimer()
  closePeerConnection()
  const video = videoElement.value
  if (!video) {
    startMjpegFallback()
    return
  }
  setConnecting('WebRTC 不可用，正在切换稳定视频')

  const { default: Hls } = await import('hls.js')
  if (generation !== connectionGeneration) {
    return
  }

  if (Hls.isSupported()) {
    hls?.destroy()
    hls = new Hls({
      lowLatencyMode: true,
      liveSyncDurationCount: 1,
      liveMaxLatencyDurationCount: 3,
      maxLiveSyncPlaybackRate: 1.5,
      xhrSetup: (xhr) => {
        xhr.withCredentials = true
      },
    })
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      if (generation !== connectionGeneration) {
        return
      }
      setMode('hls', 'WebRTC 不可用，当前使用 HLS 稳定模式')
      void video.play().catch(() => undefined)
    })
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (generation === connectionGeneration && data.fatal) {
        startMjpegFallback()
      }
    })
    hls.loadSource(currentHlsUrl)
    hls.attachMedia(video)
    return
  }

  if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.srcObject = null
    video.src = currentHlsUrl
    video.onloadedmetadata = () => {
      if (generation === connectionGeneration) {
        setMode('hls', 'WebRTC 不可用，当前使用 HLS 稳定模式')
        void video.play().catch(() => undefined)
      }
    }
    video.onerror = () => startMjpegFallback()
    return
  }
  startMjpegFallback()
}

let currentHlsUrl = ''

async function connectCloudVideo() {
  const generation = ++connectionGeneration
  if (retryTimer !== null) {
    window.clearTimeout(retryTimer)
    retryTimer = null
  }
  cleanupPlayback()
  currentHlsUrl = ''
  if (!props.apiToken.trim()) {
    startMjpegFallback('检测画面（公网访问保存 Token 后启用低延迟视频）')
    return
  }
  setConnecting('正在建立低延迟视频链路')
  try {
    const session = await createVideoSession()
    if (generation !== connectionGeneration) {
      return
    }
    currentHlsUrl = new URL(session.hls_url, window.location.href).toString()
    await startWebRtc(new URL(session.webrtc_url, window.location.href).toString(), generation)
  } catch {
    if (generation === connectionGeneration) {
      if (currentHlsUrl) {
        await startHlsFallback(generation)
      } else {
        startMjpegFallback()
      }
    }
  }
}

function startMjpegFallback(message = '云端视频暂不可用，当前显示检测画面') {
  cleanupPlayback()
  if (props.fallbackAvailable && props.fallbackUrl) {
    setMode('mjpeg', message)
  } else {
    setMode('offline', '暂无可用视频画面')
  }
  scheduleRetry()
}

function handleFallbackImageError() {
  fallbackImageFailed.value = true
  if (mode.value === 'mjpeg' || mode.value === 'connecting') {
    setMode('offline', '检测画面暂不可用，正在重试')
  }
  // 检测画面断开（网关重启、RK3588 短暂离线）后 3 秒自动重新拉流，不必等云端视频重试
  if (fallbackReloadTimer === null) {
    fallbackReloadTimer = window.setTimeout(() => {
      fallbackReloadTimer = null
      fallbackImageFailed.value = false
      fallbackReload.value += 1
      if (mode.value === 'offline' && props.fallbackAvailable && props.fallbackUrl) {
        setMode('mjpeg', '云端视频暂不可用，当前显示检测画面')
      }
    }, 3000)
  }
  scheduleRetry()
}

function scheduleRetry(delayMs?: number) {
  if (!props.apiToken.trim() || retryTimer !== null) {
    return
  }
  const wait = delayMs ?? retryDelayMs
  if (delayMs === undefined) {
    retryDelayMs = Math.min(retryDelayMs * 2, RETRY_MAX_MS)
  }
  retryTimer = window.setTimeout(() => {
    retryTimer = null
    void connectCloudVideo()
  }, wait)
}

function clearFallbackTimer() {
  if (fallbackTimer !== null) {
    window.clearTimeout(fallbackTimer)
    fallbackTimer = null
  }
}

function closePeerConnection() {
  if (whepSessionUrl) {
    void fetch(whepSessionUrl, { method: 'DELETE', credentials: 'include' }).catch(() => undefined)
    whepSessionUrl = ''
  }
  peerConnection?.close()
  peerConnection = null
}

function cleanupPlayback() {
  clearFallbackTimer()
  closePeerConnection()
  hls?.destroy()
  hls = null
  const video = videoElement.value
  if (video) {
    video.pause()
    video.removeAttribute('src')
    video.srcObject = null
    video.load()
  }
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible' && ['offline', 'mjpeg'].includes(mode.value)) {
    void connectCloudVideo()
  }
}

watch(() => props.apiToken, () => {
  retryDelayMs = RETRY_MIN_MS
  void connectCloudVideo()
})
watch(() => [props.fallbackAvailable, props.fallbackUrl], () => {
  fallbackImageFailed.value = false
  if (mode.value === 'offline' && props.fallbackAvailable) {
    startMjpegFallback()
  }
})

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  void connectCloudVideo()
})

onBeforeUnmount(() => {
  connectionGeneration += 1
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  if (retryTimer !== null) {
    window.clearTimeout(retryTimer)
  }
  if (fallbackReloadTimer !== null) {
    window.clearTimeout(fallbackReloadTimer)
  }
  cleanupPlayback()
})
</script>

<template>
  <div class="cloud-video-player">
    <video
      ref="videoElement"
      class="cloud-video-media"
      :class="{ visible: mode === 'webrtc' || mode === 'hls' }"
      autoplay
      muted
      playsinline
    ></video>
    <img
      v-if="showFallbackImage"
      class="cloud-video-media visible"
      :src="fallbackSrc"
      alt="最新识别画面"
      @error="handleFallbackImageError"
    />
    <div v-if="(mode === 'connecting' && !showFallbackImage) || mode === 'offline'" class="cloud-video-placeholder">
      {{ detail }}
    </div>
    <div class="stream-mode-plate" :data-mode="mode">
      <span class="stream-live-dot"></span>
      {{ modeLabel }}
    </div>
    <button v-if="mode === 'offline' || mode === 'mjpeg'" class="stream-retry" type="button" title="重新连接云端视频" @click="connectCloudVideo">
      重连
    </button>
    <span class="stream-detail">{{ detail }}</span>
  </div>
</template>

<style scoped>
.cloud-video-player {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  color: #fff7e8;
  background: #05090d;
}

.cloud-video-media {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  object-fit: contain;
  transition: opacity 180ms ease;
}

.cloud-video-media.visible {
  opacity: 1;
}

.cloud-video-placeholder {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  color: rgba(255, 247, 232, 0.56);
  text-align: center;
  font-size: 0.86rem;
}

.stream-mode-plate,
.stream-detail,
.stream-retry {
  position: absolute;
  z-index: 2;
}

.stream-mode-plate {
  top: 10px;
  left: 10px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 8px;
  border: 1px solid rgba(255, 247, 232, 0.18);
  border-radius: 6px;
  color: #fff7e8;
  background: rgba(6, 10, 14, 0.78);
  backdrop-filter: blur(10px);
  font: 700 0.65rem/1 var(--mono);
  letter-spacing: 0;
}

.stream-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #ffb547;
  box-shadow: 0 0 0 4px rgba(255, 181, 71, 0.16);
}

.stream-mode-plate[data-mode="webrtc"] .stream-live-dot {
  background: #3ddc84;
  box-shadow: 0 0 0 4px rgba(61, 220, 132, 0.16);
}

.stream-mode-plate[data-mode="offline"] .stream-live-dot {
  background: #8f887d;
  box-shadow: none;
}

.stream-detail {
  right: 10px;
  bottom: 9px;
  max-width: calc(100% - 20px);
  overflow: hidden;
  color: rgba(255, 247, 232, 0.62);
  font-size: 0.68rem;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-shadow: 0 1px 4px #000;
}

.stream-retry {
  top: 9px;
  right: 9px;
  min-height: 32px;
  padding: 5px 10px;
  border-color: rgba(255, 247, 232, 0.28);
  color: #fff7e8;
  background: rgba(6, 10, 14, 0.78);
}

@media (max-width: 820px) {
  .stream-retry {
    min-height: 44px;
  }

  .stream-detail {
    display: none;
  }
}
</style>
