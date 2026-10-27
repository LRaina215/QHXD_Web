import type { Tone } from './types'

export const TASK_TYPE_LABELS: Record<string, string> = {
  placeholder: '空闲',
  go_to_waypoint: '定点导航',
  start_patrol: '巡检',
  return_home: '返航',
  search_target: '寻找目标',
  follow_target: '跟随',
}

export const TASK_STATE_LABELS: Record<string, string> = {
  idle: '空闲',
  pending: '下发中',
  running: '执行中',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export const PHASE_LABELS: Record<string, string> = {
  sending_goal: '下发目标点',
  navigating: '导航中',
  dwell: '巡检点停留',
  blocked: '受阻重规划',
  searching: '探索搜索',
  tracking: '接近目标',
  verifying_arrival: '核验到达与停稳',
  waiting_stop: '等待停稳确认',
  stop_unconfirmed: '停稳未确认',
  paused: '已暂停',
  exploring: '探索搜索',
  starting: '启动中',
  completed: '已完成',
  failed: '已失败',
  cancelled: '已取消',
  idle: '等待任务',
}

export const FPGA_STATE_LABELS: Record<string, string> = {
  idle: '空闲',
  moving: '行进',
  arrived: '到达',
  blocked: '受阻',
  tracking: '跟踪',
  searching: '探索',
  estop: '急停',
}

export const FPGA_MODE_LABELS: Record<string, string> = {
  idle: '空闲', goto: '定点', track: '跟踪', search: '探索', estop: '急停',
}

export const LOC_LABELS: Record<string, string> = {
  mapless: '无图（里程计）',
  aligning: '对准中',
  ok: '正常',
  degraded: '退化',
  lost: '丢失',
}

export const CLASS_LABELS: Record<string, string> = {
  bottle: '水瓶', cup: '杯子', person: '人', 'sports ball': '球', chair: '椅子', backpack: '背包',
}

export const COLOR_LABELS: Record<string, string> = {
  red: '红', green: '绿', blue: '蓝', yellow: '黄', white: '白', black: '黑', other: '其他',
}

export const COLOR_SWATCH: Record<string, string> = {
  red: '#ff4d5e', green: '#3ddc84', blue: '#4c8dff', yellow: '#ffd23f', white: '#f2f5f7', black: '#2b3036',
}

export function taskTone(state: string | undefined): Tone {
  if (state === 'running' || state === 'pending') return 'run'
  if (state === 'completed') return 'ok'
  if (state === 'failed') return 'bad'
  if (state === 'paused') return 'wait'
  return 'off'
}

export function linkTone(link: string | undefined | null): Tone {
  if (link === 'online') return 'ok'
  if (link === 'mock') return 'mock'
  if (link === 'offline') return 'bad'
  return 'off'
}

export function linkLabel(link: string | undefined | null): string {
  return ({ online: '在线', mock: '模拟', offline: '离线', unknown: '未接入' } as Record<string, string>)[link ?? 'unknown'] ?? '未接入'
}

export function levelTone(level: string | undefined): Tone {
  const v = (level ?? '').toLowerCase()
  if (['error', 'critical', 'danger', 'failed'].some((k) => v.includes(k))) return 'bad'
  if (['warn', 'blocked'].some((k) => v.includes(k))) return 'warn'
  if (['paused', 'cancelled', 'lost'].some((k) => v.includes(k))) return 'wait'
  if (['completed', 'arrived', 'found', 'ok'].some((k) => v.includes(k))) return 'ok'
  return 'run'
}

export function fmt(value: number | null | undefined, digits = 2, suffix = ''): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return `${value.toFixed(digits)}${suffix}`
}

export function clock(value: string | null | undefined): string {
  if (!value) return '--'
  return new Date(value).toLocaleTimeString('zh-CN', { hour12: false })
}

export function targetLabel(cls: string, color?: string | null): string {
  const c = color ? `${COLOR_LABELS[color] ?? color}色` : ''
  return `${c}${CLASS_LABELS[cls] ?? cls}`
}
