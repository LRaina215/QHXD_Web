export type Tone = 'ok' | 'info' | 'warn' | 'danger' | 'muted'

export type DetectionObject = {
  class_name: string
  confidence: number
  bbox_xyxy: number[]
  current_frame?: boolean
  recently_seen?: boolean
  age_s?: number | null
  track_id?: number | null
  color?: string | null
  position_body_m?: number[] | null
  distance_m?: number | null
}

export type DetectionStatus = {
  enabled: boolean
  source: string
  model_name: string | null
  frame_id: string
  timestamp: string
  objects: DetectionObject[]
  events: Array<{ event_type: string; level: string; message: string }>
}

export type PlatformStatus = {
  source: string
  updated_at: string
  nav_link: string
  nav_link_kind: string | null
  fpga_mode: string | null
  fpga_state: string | null
  loc_state: string | null
  loc_quality: number | null
  map_loaded: boolean
  target_valid: boolean
  lidar_ok: boolean | null
  odom_ok: boolean | null
  cmd_vx_mps: number | null
  cmd_wz_radps: number | null
  fpga_uptime_s: number | null
  status_rate_hz: number | null
  control_link: string
  policy_active: boolean | null
  control_estop: boolean | null
  control_faults: string[]
  wheel_left_mps: number | null
  wheel_right_mps: number | null
  roll_deg: number | null
  pitch_deg: number | null
  yaw_rate_radps: number | null
  height_cmd_m: number | null
  telemetry_rate_hz: number | null
}

export type TaskStatus = {
  task_id: string
  task_type: string
  state: string
  progress: number
  source: string
  phase?: string | null
  current_waypoint_id?: string | null
  waypoint_index?: number | null
  waypoint_count?: number | null
  detail?: string | null
  updated_at?: string | null
}

export type RobotState = {
  robot_pose: { x: number; y: number; yaw: number; frame_id: string; timestamp: string }
  nav_status: { mode: string; state: string; current_goal: string | null; remaining_distance: number | null }
  task_status: TaskStatus
  device_status: { battery_percent: number | null; emergency_stop: boolean; fault_code: string | null; online: boolean }
  env_sensor: { temperature_c: number | null; humidity_percent: number | null; status: string }
  system_mode: { mode: string; updated_at: string }
  detection_status: DetectionStatus | null
  platform_status?: PlatformStatus | null
  updated_at: string
}

export type Point = { x: number; y: number }
export type Pose = Point & { yaw: number }

export type NavigationSnapshot = {
  source: string
  frame_id: string
  timestamp: string
  sequence: number
  map_version: string | null
  pose: Pose | null
  goal: Pose | null
  velocity: { vx: number; vy: number; wz: number } | null
  global_path: Point[]
  local_path: Point[]
  nav_state: string
  remaining_distance: number | null
  target?: Point | null
}

export type MapMetadata = {
  map_id: string
  version: string
  frame_id: string
  resolution: number
  width: number
  height: number
  origin: { x: number; y: number; yaw: number }
}

export type Waypoint = {
  waypoint_id: string
  name: string
  aliases: string[]
  map_id: string
  pose: Pose | null
  group: string
  enabled: boolean
  configured: boolean
}

export type AlertEvent = { alert_id: string; level: string; message: string; source: string; timestamp: string }

export type TaskEvent = {
  event_id: string
  task_id: string
  event_type: string
  task_state: string
  detail: string
  source: string
  progress: number
  timestamp: string
}

export type PayloadValue = string | number | boolean | null

export type PendingCommand = {
  recognized_text?: string
  intent?: string | null
  command?: string | null
  waypoint_id?: string | null
  payload?: Record<string, PayloadValue>
  confidence?: number
  parser?: string
  llm_backend?: string | null
  llm_model?: string | null
  detail?: string
  pending_command_id?: string | null
}

export type SmartCommandResult = {
  request_id: string
  recognized_text: string
  intent: string | null
  data_source: string | null
  reply_text: string
  need_confirm: boolean
  mission_candidate: {
    command: string
    payload: Record<string, PayloadValue>
    pending_command_id: string | null
    detail: string
  } | null
  pending_command_id: string | null
  error_reason: string | null
  confidence: number
  parser: string
  llm_backend?: string | null
  llm_model?: string | null
  timestamp: string
}

export type LogLine = { id: string; time: string; tone: Tone; source: string; text: string }
