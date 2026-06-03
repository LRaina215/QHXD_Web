const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? ''
const rawWsStateUrl = import.meta.env.VITE_WS_STATE_URL ?? ''
const rawWsImuUrl = import.meta.env.VITE_WS_IMU_URL ?? ''

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '')
}

function normalizePath(path: string): string {
  return path.startsWith('/') ? path : `/${path}`
}

function sameOriginWsUrl(path: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}${normalizePath(path)}`
}

export const API_BASE_URL = trimTrailingSlash(rawApiBaseUrl)
export const WS_STATE_URL = rawWsStateUrl
export const WS_IMU_URL = rawWsImuUrl
export const ENABLE_LOCAL_RECORD_COMMAND = ['1', 'true', 'yes', 'on'].includes(
  String(import.meta.env.VITE_ENABLE_LOCAL_RECORD_COMMAND ?? '').toLowerCase(),
)

export function apiUrl(path: string): string {
  const normalizedPath = normalizePath(path)
  if (!API_BASE_URL) {
    return normalizedPath
  }
  return `${API_BASE_URL}${normalizedPath}`
}

export function wsUrl(path: string): string {
  const normalizedPath = normalizePath(path)
  if (normalizedPath === '/ws/state' && WS_STATE_URL) {
    return WS_STATE_URL
  }
  if (normalizedPath === '/ws/imu' && WS_IMU_URL) {
    return WS_IMU_URL
  }
  return sameOriginWsUrl(normalizedPath)
}

export function perceptionFrameStreamUrl(): string {
  return apiUrl(`/api/perception/frame_stream?t=${Date.now()}`)
}

export function perceptionLatestFrameUrl(): string {
  return apiUrl(`/api/perception/latest_frame?t=${Date.now()}`)
}

export function authHeaders(): Record<string, string> {
  const token = String(
    import.meta.env.VITE_PUBLIC_API_TOKEN
      || window.localStorage.getItem('qhxd_api_token')
      || '',
  ).trim()

  if (!token) {
    return {}
  }

  return {
    Authorization: `Bearer ${token}`,
  }
}
