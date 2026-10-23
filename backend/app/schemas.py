from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JsonScalar = str | int | float | bool | None

SystemModeValue = Literal["mock", "real"]
NavModeValue = Literal["auto", "manual"]
NavStateValue = Literal["idle", "running", "paused", "completed", "failed", "offline"]
TaskTypeValue = Literal[
    "placeholder", "go_to_waypoint", "start_patrol", "return_home", "search_target", "follow_target"
]
TaskStateValue = Literal["idle", "pending", "running", "paused", "completed", "failed", "cancelled"]
SensorStatusValue = Literal["mock", "nominal", "warning", "fault", "offline"]
AlertLevelValue = Literal["info", "warning", "error", "critical"]
MissionCommandValue = Literal[
    "go_to_waypoint", "start_patrol", "pause_task", "resume_task", "cancel_task", "return_home",
    "search_target", "follow_target",
]
VoiceIntentValue = Literal[
    "go_to_waypoint",
    "start_patrol",
    "pause_task",
    "resume_task",
    "return_home",
    "search_target",
    "follow_target",
    "query_status",
    "query_task",
    "query_detection",
    "query_self_identity",
    "query_capability",
    "query_safety_rule",
    "query_assistant_model",
    "query_robot_status",
    "query_task_status",
    "query_navigation_status",
    "query_battery",
    "query_emergency_stop",
    "query_perception_status",
    "query_front_status",
    "query_obstacle_status",
    "query_navigation_safety",
    "query_weather",
    "query_environment",
    "speak_last_result",
    "open_chat",
    "unknown",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ContractModel):
    status: str = Field(default="ok")


class SystemMode(ContractModel):
    mode: SystemModeValue = Field(description="系统模式：mock 或 real")
    updated_at: datetime = Field(description="模式更新时间")


class RobotPose(ContractModel):
    x: float = Field(default=0.0, description="机器人横坐标，单位 m")
    y: float = Field(default=0.0, description="机器人纵坐标，单位 m")
    yaw: float = Field(default=0.0, description="机器人朝向角，单位 rad")
    frame_id: str = Field(default="map", description="坐标系名称")
    timestamp: datetime = Field(description="位姿更新时间")


class NavStatus(ContractModel):
    mode: NavModeValue = Field(default="auto", description="导航模式")
    state: NavStateValue = Field(default="idle", description="导航状态")
    current_goal: str | None = Field(default=None, description="当前目标点 ID")
    remaining_distance: float | None = Field(default=None, description="剩余距离，单位 m")


class NavigationPoint(ContractModel):
    x: float = Field(description="map 坐标系 X，单位 m")
    y: float = Field(description="map 坐标系 Y，单位 m")


class NavigationPose(NavigationPoint):
    yaw: float = Field(default=0.0, description="车体朝向，单位 rad")


class NavigationVelocity(ContractModel):
    vx: float = Field(default=0.0, description="X 方向速度，单位 m/s")
    vy: float = Field(default=0.0, description="Y 方向速度，单位 m/s")
    wz: float = Field(default=0.0, description="角速度，单位 rad/s")


class NavigationSnapshot(ContractModel):
    source: str = Field(default="rk3588-ros2-navigation-web-bridge")
    frame_id: str = Field(default="map")
    timestamp: datetime
    sequence: int = Field(default=0, ge=0)
    map_version: str | None = None
    pose: NavigationPose | None = None
    goal: NavigationPose | None = None
    velocity: NavigationVelocity | None = None
    global_path: list[NavigationPoint] = Field(default_factory=list)
    local_path: list[NavigationPoint] = Field(default_factory=list)
    nav_state: str = Field(default="waiting")
    remaining_distance: float | None = Field(default=None, ge=0.0)
    target: NavigationPoint | None = Field(default=None, description="正在接近 / 跟随的视觉目标（map 坐标系）")


class NavigationMapOrigin(ContractModel):
    x: float
    y: float
    yaw: float = 0.0


class NavigationMapUpdateRequest(ContractModel):
    map_id: str = Field(default="navigation-map")
    version: str
    frame_id: str = Field(default="map")
    timestamp: datetime
    resolution: float = Field(gt=0.0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    origin: NavigationMapOrigin
    data: list[int] = Field(description="ROS OccupancyGrid data：-1 未知，0~100 占用率")


class NavigationMapMetadata(ContractModel):
    map_id: str
    version: str
    frame_id: str
    timestamp: datetime
    resolution: float
    width: int
    height: int
    origin: NavigationMapOrigin
    image_url: str = Field(default="/api/navigation/map/image")


class NavigationLatestResponse(ContractModel):
    success: bool = True
    data: NavigationSnapshot | None


class NavigationMapMetadataResponse(ContractModel):
    success: bool = True
    data: NavigationMapMetadata


class NavigationUpdateResult(ContractModel):
    accepted: bool = True
    updated_at: datetime
    detail: str


class NavigationUpdateResponse(ContractModel):
    success: bool = True
    data: NavigationUpdateResult


class TaskStatus(ContractModel):
    task_id: str = Field(default="mock-task", description="任务 ID")
    task_type: TaskTypeValue = Field(default="placeholder", description="任务类型")
    state: TaskStateValue = Field(default="idle", description="任务状态")
    progress: int = Field(default=0, ge=0, le=100, description="任务进度，百分比")
    source: str = Field(default="web", description="任务来源")
    phase: str | None = Field(default=None, description="任务当前阶段")
    current_waypoint_id: str | None = Field(default=None, description="当前点位 ID")
    waypoint_index: int | None = Field(default=None, ge=0, description="当前巡检点序号，从 0 开始")
    waypoint_count: int | None = Field(default=None, ge=0, description="巡检点总数")
    detail: str | None = Field(default=None, description="最近任务状态说明")
    updated_at: datetime | None = Field(default=None, description="任务状态更新时间")


class DeviceStatus(ContractModel):
    # Real 模式映射约定：
    # device_status 由 RK3588 本机真实链路归一化后提供，
    # 后端继续复用该公开契约，不新增 C 板平行字段。
    battery_percent: int | None = Field(default=100, ge=0, le=100, description="电量百分比")
    emergency_stop: bool = Field(default=False, description="急停状态")
    fault_code: str | None = Field(default=None, description="故障码")
    online: bool = Field(default=True, description="节点在线状态")


class EnvSensor(ContractModel):
    # Real 模式映射约定：
    # 若真实环境传感器未就绪，允许上送 null 值占位，并以 status 表示可用性。
    temperature_c: float | None = Field(default=25.0, description="温度，单位摄氏度")
    humidity_percent: float | None = Field(default=45.0, description="湿度百分比")
    status: SensorStatusValue = Field(default="mock", description="传感器状态")


class AlertEvent(ContractModel):
    alert_id: str = Field(description="告警 ID")
    level: AlertLevelValue = Field(description="告警级别")
    message: str = Field(description="告警内容")
    source: str = Field(description="告警来源")
    timestamp: datetime = Field(description="告警时间")
    acknowledged: bool = Field(default=False, description="是否已确认")


class DetectionObject(ContractModel):
    class_name: str = Field(description="检测类别名称")
    confidence: float = Field(ge=0.0, le=1.0, description="检测置信度")
    bbox_xyxy: list[float] = Field(description="目标框，格式为 [x1, y1, x2, y2]")
    current_frame: bool = Field(default=True, description="是否为当前帧直接检测到的目标")
    recently_seen: bool = Field(default=False, description="是否为短时保持的最近目标")
    last_seen_at: datetime | None = Field(default=None, description="短时保持目标上次被检测到的时间")
    age_s: float | None = Field(default=None, ge=0.0, description="距离上次检测到的秒数")
    track_id: int | None = Field(default=None, ge=0, description="跟踪 ID，同一目标在相邻帧保持不变")
    color: str | None = Field(default=None, description="框内主色：red / green / blue / yellow / white / black / other")
    position_body_m: list[float] | None = Field(
        default=None, min_length=3, max_length=3, description="机身系目标位置 [x 前, y 左, z 上]，单位 m；无深度时为空"
    )
    distance_m: float | None = Field(default=None, ge=0.0, description="目标水平距离，单位 m")


LinkStateValue = Literal["online", "offline", "mock", "unknown"]


class ControlTelemetry(ContractModel):
    """完整原控制帧；raw字段与导航ICD的CONTROL_V2一致，不据此单独判定实车停稳。"""
    transport: Literal["nv_udp", "legacy_telemetry"]
    source: Literal["fpga", "mock"]
    version: Literal[1, 2]
    fresh: bool
    receive_age_ms: float = Field(ge=0)
    measurement_age_ms: float | None = None
    raw: dict[str, int]


class PlatformStatus(ContractModel):
    """云拓整车 FPGA 侧状态：导航（NV STATUS 报文）与控制（V2 遥测），由 fpga_bridge 上送。"""

    source: str = Field(default="fpga_bridge")
    updated_at: datetime = Field(description="最近一次刷新时间")
    nav_link: LinkStateValue = Field(default="unknown", description="FPGA 导航链路")
    nav_link_kind: str | None = Field(default=None, description="链路类型，例如 uart:/dev/ttyACM0、udp:127.0.0.1:9000")
    fpga_mode: str | None = Field(default=None, description="FPGA 导航模式：idle / goto / track / search / estop")
    fpga_state: str | None = Field(
        default=None, description="FPGA 导航状态：idle / moving / arrived / blocked / tracking / searching / estop"
    )
    loc_state: str | None = Field(default=None, description="定位状态：mapless / aligning / ok / degraded / lost")
    loc_quality: int | None = Field(default=None, ge=0, le=100, description="有图定位质量，百分比")
    map_loaded: bool = Field(default=False, description="FPGA 是否已加载先验地图")
    target_valid: bool = Field(default=False, description="FPGA 当前是否持有有效视觉目标")
    lidar_ok: bool | None = Field(default=None, description="雷达代价图是否正常")
    odom_ok: bool | None = Field(default=None, description="里程计是否正常")
    cmd_vx_mps: float | None = Field(default=None, description="导航当前期望前进速度 m/s")
    cmd_wz_radps: float | None = Field(default=None, description="导航当前期望角速度 rad/s（左转为正）")
    fpga_uptime_s: float | None = Field(default=None, ge=0.0, description="FPGA 计时（32 位微秒计数换算）")
    status_rate_hz: float | None = Field(default=None, ge=0.0, description="STATUS 报文实际接收频率")
    control_link: LinkStateValue = Field(default="unknown", description="FPGA 控制遥测链路")
    policy_active: bool | None = Field(default=None, description="RL 策略是否在运行")
    control_estop: bool | None = Field(default=None, description="控制侧急停锁存")
    control_faults: list[str] = Field(default_factory=list, description="控制侧故障标志")
    wheel_left_mps: float | None = Field(default=None, description="左轮编码器速度 m/s（前进为正）")
    wheel_right_mps: float | None = Field(default=None, description="右轮编码器速度 m/s（前进为正）")
    roll_deg: float | None = Field(default=None, description="横滚角 deg")
    pitch_deg: float | None = Field(default=None, description="俯仰角 deg")
    yaw_rate_radps: float | None = Field(default=None, description="偏航角速度 rad/s")
    height_cmd_m: float | None = Field(default=None, description="当前底盘高度指令 m")
    telemetry_rate_hz: float | None = Field(default=None, ge=0.0, description="控制遥测实际接收频率")
    control_telemetry: ControlTelemetry | None = Field(default=None, description="原控制完整遥测，过期保留原值但fresh=false")


class PlatformStatusUpdateRequest(ContractModel):
    platform_status: PlatformStatus


class PlatformStatusResponse(ContractModel):
    success: bool = Field(default=True)
    data: PlatformStatus | None


class PlatformEstopRequest(ContractModel):
    engage: bool = Field(default=True, description="true 触发急停（MODE estop）；false 解除导航急停（MODE idle）")
    source: str = Field(default="web")
    requested_by: str | None = None


class PlatformSetPoseRequest(ContractModel):
    x: float = Field(description="地图系 X，m")
    y: float = Field(description="地图系 Y，m")
    yaw: float = Field(default=0.0, description="朝向，rad")
    align: bool = Field(default=True, description="有图时在先验图上搜索对准")
    source: str = Field(default="web")
    requested_by: str | None = None


class PlatformCommandResult(ContractModel):
    accepted: bool
    command: str
    detail: str
    received_at: datetime


class PlatformCommandResponse(ContractModel):
    success: bool = True
    data: PlatformCommandResult


class DetectionEvent(ContractModel):
    event_type: str = Field(description="检测事件类型")
    level: AlertLevelValue = Field(default="info", description="事件级别")
    message: str = Field(description="事件说明")


class DetectionStatus(ContractModel):
    enabled: bool = Field(default=True, description="本地检测链路是否启用")
    source: str = Field(default="rk3588-rknn-yolo", description="检测状态来源")
    model_name: str | None = Field(default=None, description="模型文件名")
    frame_id: str = Field(default="camera_front", description="图像坐标系或相机 ID")
    timestamp: datetime = Field(description="检测状态更新时间")
    objects: list[DetectionObject] = Field(default_factory=list, description="最近检测目标")
    events: list[DetectionEvent] = Field(default_factory=list, description="检测派生事件")


class VisualEventRecord(ContractModel):
    event_id: str
    event_type: str
    level: AlertLevelValue = "info"
    class_name: str | None = None
    message: str
    source: str = "visual_event_store"
    task_id: str | None = None
    waypoint_id: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    duration_s: float = Field(default=0.0, ge=0.0)
    max_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    count: int = Field(default=1, ge=1)
    status: str = Field(default="active")


class VisualEventsResponse(ContractModel):
    success: bool = True
    data: list[VisualEventRecord]


class VideoHealthStatus(ContractModel):
    status: str
    latest_frame_path: str | None = None
    latest_frame_age_s: float | None = None
    latest_frame_fresh: bool = False
    detection_enabled: bool | None = None
    detection_updated_at: datetime | None = None
    detection_age_s: float | None = None
    yolo_camera_pid: int | None = None
    yolo_camera_running: bool = False
    stream_url: str | None = None
    perception: dict[str, Any] | None = Field(default=None, description="云拓感知节点自报状态：检测帧率、推流计数")
    recent_visual_events: list[VisualEventRecord] = Field(default_factory=list)
    detail: str
    updated_at: datetime


class VideoHealthResponse(ContractModel):
    success: bool = True
    data: VideoHealthStatus


class RobotState(ContractModel):
    robot_pose: RobotPose
    nav_status: NavStatus
    task_status: TaskStatus
    device_status: DeviceStatus
    env_sensor: EnvSensor
    system_mode: SystemMode
    detection_status: DetectionStatus | None = Field(default=None, description="可选本地视觉检测状态")
    platform_status: PlatformStatus | None = Field(default=None, description="云拓 FPGA 导航与控制链路状态")
    updated_at: datetime = Field(description="状态更新时间")


class StateLatestResponse(ContractModel):
    success: bool = Field(default=True)
    data: RobotState


class AlertsResponse(ContractModel):
    success: bool = Field(default=True)
    data: list[AlertEvent]


class CurrentTaskResponse(ContractModel):
    success: bool = Field(default=True)
    data: TaskStatus


class RobotProfile(ContractModel):
    robot_name: str
    english_name: str
    full_name: str
    role: str
    team: str
    abilities: list[str]
    safety_rules: list[str]
    self_intro: str


class WeatherData(ContractModel):
    location: str
    temperature_c: float | None = None
    apparent_temperature_c: float | None = None
    humidity_percent: float | None = None
    precipitation_mm: float | None = None
    precipitation_probability_percent: float | None = None
    uv_index: float | None = None
    weather: str
    wind: str | None = None
    source: str = Field(default="weather_provider")
    is_stale: bool = False
    advice: str | None = None
    updated_at: datetime


class ExternalWeatherLatestResponse(ContractModel):
    success: bool = Field(default=True)
    data: WeatherData | None = None
    error: str | None = None
    detail: str | None = None


class MissionRequestBase(ContractModel):
    source: str = Field(default="web", description="命令来源")
    requested_by: str | None = Field(default=None, description="命令发起人")


class GoToWaypointRequest(MissionRequestBase):
    waypoint_id: str = Field(description="目标点 ID")


class StartPatrolRequest(MissionRequestBase):
    patrol_id: str = Field(description="巡检路线 ID")


class PauseMissionRequest(MissionRequestBase):
    pass


class ResumeMissionRequest(MissionRequestBase):
    pass


class ReturnHomeRequest(MissionRequestBase):
    pass


class CancelMissionRequest(MissionRequestBase):
    pass


TargetColorValue = Literal["red", "green", "blue", "yellow", "white", "black", "other"]


class SearchTargetRequest(MissionRequestBase):
    """探索场地找指定目标，找到后由 FPGA 自主接近并停在目标前（站位约 0.7 m）。"""

    target_class: str = Field(min_length=1, description="检测类别，取自模型 labels，例如 bottle、person、cup")
    color: TargetColorValue | None = Field(default=None, description="可选颜色约束，例如 red")
    label: str | None = Field(default=None, description="展示名，例如 红色水瓶")
    timeout_s: int = Field(default=180, ge=10, le=900, description="超过该时间仍未完成即判失败")


class FollowTargetRequest(MissionRequestBase):
    """持续跟随指定目标（例如人员），目标丢失后回到探索继续找。"""

    target_class: str = Field(default="person", min_length=1, description="检测类别")
    color: TargetColorValue | None = Field(default=None, description="可选颜色约束")
    label: str | None = Field(default=None, description="展示名")
    timeout_s: int = Field(default=300, ge=10, le=1800, description="跟随任务总时长上限")


class WaypointPose(ContractModel):
    x: float
    y: float
    yaw: float = 0.0


class WaypointDefinition(ContractModel):
    waypoint_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    map_id: str = Field(default="sentinel_map")
    pose: WaypointPose | None = None
    group: str = Field(default="navigation")
    enabled: bool = True
    configured: bool = False


class WaypointsResponse(ContractModel):
    success: bool = True
    data: list[WaypointDefinition]


class WaypointResponse(ContractModel):
    success: bool = True
    data: WaypointDefinition


class TaskEvent(ContractModel):
    event_id: str
    task_id: str
    event_type: str
    task_state: TaskStateValue
    detail: str
    source: str = Field(default="nav2_mission_executor")
    waypoint_id: str | None = None
    remaining_distance: float | None = Field(default=None, ge=0.0)
    progress: int = Field(default=0, ge=0, le=100)
    timestamp: datetime


class TaskEventsResponse(ContractModel):
    success: bool = True
    data: list[TaskEvent]


class MissionActionResult(ContractModel):
    accepted: bool = Field(default=True)
    command: str = Field(description="命令名称")
    task_status: TaskStatus
    received_at: datetime = Field(description="命令接收时间")
    detail: str = Field(description="命令处理说明")


class MissionActionResponse(ContractModel):
    success: bool = Field(default=True)
    data: MissionActionResult


class MissionExecutorUpdateRequest(ContractModel):
    event: TaskEvent
    task_status: TaskStatus
    current_goal: str | None = None
    nav_state: NavStateValue = "idle"


class MissionExecutorUpdateResult(ContractModel):
    accepted: bool = True
    state_updated: bool = True
    duplicate: bool = False
    detail: str


class MissionExecutorUpdateResponse(ContractModel):
    success: bool = True
    data: MissionExecutorUpdateResult


class VoiceTextCommandRequest(ContractModel):
    text: str = Field(min_length=1, description="文本命令内容")
    source: str = Field(default="text-debug", description="命令来源")
    requested_by: str | None = Field(default=None, description="命令发起人")
    use_llm: bool | None = Field(default=None, description="本次请求是否允许 LLM fallback；false 会强制禁用")


class VoiceCommandResult(ContractModel):
    accepted: bool = Field(description="是否已受理或成功查询")
    intent: VoiceIntentValue | None = Field(default=None, description="解析出的意图")
    command: str | None = Field(default=None, description="实际任务命令或查询命令")
    payload: dict[str, JsonScalar] = Field(default_factory=dict, description="解析出的命令参数")
    confidence: float = Field(ge=0.0, le=1.0, description="解析置信度")
    need_confirm: bool = Field(default=False, description="是否需要人工确认")
    detail: str = Field(description="解析或执行说明")
    task_status: TaskStatus | None = Field(default=None, description="任务执行后的任务状态")
    parser: str = Field(default="rule", description="解析器来源：rule / llm / safety")
    llm_backend: str | None = Field(default=None, description="LLM backend 名称")
    llm_model: str | None = Field(default=None, description="LLM 模型名称")
    llm_raw_output: str | None = Field(default=None, description="调试模式下返回的 LLM 原始输出")
    pending_command_id: str | None = Field(default=None, description="待确认命令 ID")


class VoiceCommandResponse(ContractModel):
    success: bool = Field(default=True)
    data: VoiceCommandResult


class VoiceAudioCommandResult(ContractModel):
    recognized_text: str = Field(default="", description="ASR 识别出的清洗后文本")
    raw_text: str | None = Field(default=None, description="ASR 原始文本")
    asr_backend: str = Field(description="ASR backend 名称")
    asr_time_s: float | None = Field(default=None, description="ASR 识别耗时，单位秒")
    model_load_time_s: float | None = Field(default=None, description="模型加载耗时，单位秒")
    intent: VoiceIntentValue | None = Field(default=None, description="解析出的意图")
    command: str | None = Field(default=None, description="实际任务命令或查询命令")
    payload: dict[str, JsonScalar] = Field(default_factory=dict, description="解析出的命令参数")
    waypoint_id: str | None = Field(default=None, description="解析出的目标点 ID")
    accepted: bool = Field(default=False, description="是否已受理或成功查询")
    need_confirm: bool = Field(default=True, description="是否需要人工确认")
    detail: str = Field(description="ASR、解析或执行说明")
    error: str | None = Field(default=None, description="失败原因")
    task_status: TaskStatus | None = Field(default=None, description="任务执行后的任务状态")
    parser: str = Field(default="rule", description="解析器来源：rule / llm / safety")
    llm_backend: str | None = Field(default=None, description="LLM backend 名称")
    llm_model: str | None = Field(default=None, description="LLM 模型名称")
    llm_raw_output: str | None = Field(default=None, description="调试模式下返回的 LLM 原始输出")
    pending_command_id: str | None = Field(default=None, description="待确认命令 ID")


class VoiceAudioCommandResponse(ContractModel):
    success: bool = Field(default=True)
    data: VoiceAudioCommandResult


class VoiceRecordCommandRequest(ContractModel):
    duration: int | None = Field(default=None, ge=1, le=10, description="录音时长，单位秒")
    source: str = Field(default="rk3588-record-command", description="命令来源")
    requested_by: str | None = Field(default="operator", description="命令发起人")
    keep_audio: bool | None = Field(default=None, description="是否保留录音文件")
    use_llm: bool | None = Field(default=None, description="本次请求是否允许 LLM fallback；false 会强制禁用")


class VoiceRecordCommandResult(VoiceAudioCommandResult):
    audio_path: str | None = Field(default=None, description="录音文件路径")
    duration: int = Field(description="实际录音时长，单位秒")
    audio_device: str = Field(description="arecord 使用的音频设备")
    audio_retained: bool = Field(default=True, description="录音文件是否已保留")


class VoiceRecordCommandResponse(ContractModel):
    success: bool = Field(default=True)
    data: VoiceRecordCommandResult | None = Field(default=None)
    error: str | None = Field(default=None)
    detail: str | None = Field(default=None)




class VoiceConfirmCommandRequest(ContractModel):
    pending_command_id: str = Field(min_length=1, description="待确认命令 ID")
    confirmed: bool = Field(description="true 执行，false 取消")
    requested_by: str | None = Field(default="operator", description="确认操作人")
    source: str | None = Field(default=None, description="确认来源（可选；网页 / 小程序统一带 source，这里只接受不使用）")


class VoiceConfirmCommandResponse(ContractModel):
    success: bool = Field(default=True)
    data: VoiceCommandResult


class MissionCandidate(ContractModel):
    command: MissionCommandValue
    payload: dict[str, JsonScalar] = Field(default_factory=dict)
    pending_command_id: str | None = None
    detail: str


class TTSStatus(ContractModel):
    backend: str = Field(default="mock")
    status: str = Field(default="idle")
    text: str | None = None
    audio_path: str | None = None
    audio_url: str | None = None
    detail: str | None = None
    error_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SmartCommandRequest(ContractModel):
    text: str = Field(min_length=1, description="文本或 ASR 识别结果")
    source: str = Field(default="smart-command", description="命令来源")
    requested_by: str | None = Field(default=None, description="命令发起人")
    use_llm: bool | None = Field(default=None, description="是否允许 DeepSeek fallback")
    generate_tts: bool = Field(default=False, description="是否为 reply_text 生成 TTS")


class SmartCommandResult(ContractModel):
    request_id: str
    recognized_text: str
    intent: VoiceIntentValue | None = None
    data_source: str | None = None
    reply_text: str
    need_confirm: bool = False
    mission_candidate: MissionCandidate | None = None
    pending_command_id: str | None = None
    tts_status: TTSStatus | None = None
    error_reason: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    parser: str = Field(default="rule")
    llm_backend: str | None = None
    llm_model: str | None = None
    timestamp: datetime


class SmartCommandResponse(ContractModel):
    success: bool = Field(default=True)
    data: SmartCommandResult


class SpeakRequest(ContractModel):
    text: str = Field(min_length=1, description="需要播报的文本")
    source: str = Field(default="dashboard", description="播报来源")
    requested_by: str | None = Field(default=None, description="请求人")


class SpeakResponse(ContractModel):
    success: bool = Field(default=True)
    data: TTSStatus


class TTSLatestResponse(ContractModel):
    success: bool = Field(default=True)
    data: TTSStatus | None = None


class ModeSwitchRequest(ContractModel):
    mode: SystemModeValue = Field(description="目标系统模式")
    source: str = Field(default="web", description="切换来源")
    requested_by: str | None = Field(default=None, description="切换发起人")


class ModeSwitchResult(ContractModel):
    accepted: bool = Field(default=True)
    system_mode: SystemMode
    received_at: datetime = Field(description="模式切换接收时间")
    detail: str = Field(description="模式切换说明")


class ModeSwitchResponse(ContractModel):
    success: bool = Field(default=True)
    data: ModeSwitchResult


class NucStateUpdateRequest(ContractModel):
    # 兼容历史 internal/nuc 路由名称；当前语义是 Real 模式真实状态上送：
    # - robot_pose / nav_status / task_status 来自导航与任务执行链路
    # - device_status / optional env_sensor 来自 C 板/传感器链路归一化结果
    robot_pose: RobotPose
    nav_status: NavStatus
    task_status: TaskStatus
    device_status: DeviceStatus
    env_sensor: EnvSensor
    alerts: list[AlertEvent] = Field(default_factory=list, description="随状态一并上送的告警列表")
    updated_at: datetime = Field(description="状态更新时间")


class NucStateUpdateResult(ContractModel):
    accepted: bool = Field(description="是否已被当前模式接收")
    system_mode: SystemMode
    state_updated: bool = Field(description="是否已刷新共享状态")
    received_at: datetime = Field(description="真实状态接收时间")
    detail: str = Field(description="状态接收说明")


class NucStateUpdateResponse(ContractModel):
    success: bool = Field(default=True)
    data: NucStateUpdateResult


class QuaternionSample(ContractModel):
    x: float = Field(default=0.0, description="四元数 x")
    y: float = Field(default=0.0, description="四元数 y")
    z: float = Field(default=0.0, description="四元数 z")
    w: float = Field(default=1.0, description="四元数 w")


class Vector3Sample(ContractModel):
    x: float = Field(default=0.0, description="向量 x")
    y: float = Field(default=0.0, description="向量 y")
    z: float = Field(default=0.0, description="向量 z")


class EulerDegSample(ContractModel):
    yaw: float = Field(default=0.0, description="偏航角，单位 deg")
    pitch: float = Field(default=0.0, description="俯仰角，单位 deg")
    roll: float = Field(default=0.0, description="横滚角，单位 deg")


class ImuSample(ContractModel):
    frame_id: str = Field(description="IMU 坐标系")
    timestamp: datetime = Field(description="IMU 样本时间")
    orientation: QuaternionSample
    euler_deg: EulerDegSample | None = Field(default=None, description="欧拉角，单位 deg")
    angular_velocity: Vector3Sample
    linear_acceleration: Vector3Sample


class ImuEnvelope(ContractModel):
    source: str = Field(default="rtt", description="IMU 来源")
    updated_at: datetime = Field(description="IMU 更新时间")
    imu: ImuSample


class NucImuUpdateRequest(ContractModel):
    source: str = Field(default="rtt", description="IMU 来源")
    updated_at: datetime = Field(description="IMU 更新时间")
    imu: ImuSample


class NucImuUpdateResult(ContractModel):
    accepted: bool = Field(description="是否已接收该 IMU 样本")
    system_mode: SystemMode
    imu_updated: bool = Field(description="是否已刷新最新 IMU")
    received_at: datetime = Field(description="IMU 接收时间")
    detail: str = Field(description="IMU 接收说明")


class NucImuUpdateResponse(ContractModel):
    success: bool = Field(default=True)
    data: NucImuUpdateResult


class ImuLatestResponse(ContractModel):
    success: bool = Field(default=True)
    data: ImuEnvelope | None


class PerceptionDetectionStatusRequest(ContractModel):
    detection_status: DetectionStatus


class PerceptionDetectionStatusResult(ContractModel):
    accepted: bool = Field(description="是否已接收检测状态")
    state_updated: bool = Field(description="是否已刷新共享状态")
    received_at: datetime = Field(description="检测状态接收时间")
    detail: str = Field(description="检测状态处理说明")


class PerceptionDetectionStatusResponse(ContractModel):
    success: bool = Field(default=True)
    data: PerceptionDetectionStatusResult


class NucMissionCommandRequest(ContractModel):
    command: MissionCommandValue = Field(description="转发到真实任务执行链路的命令名称")
    source: str = Field(default="web", description="命令来源")
    requested_by: str | None = Field(default=None, description="命令发起人")
    payload: dict[str, JsonScalar] = Field(default_factory=dict, description="命令参数")


class NucMissionCommandResult(ContractModel):
    accepted: bool = Field(description="真实任务执行链路是否已受理该命令")
    command: MissionCommandValue = Field(description="真实任务执行链路已处理的命令名称")
    task_status: TaskStatus
    current_goal: str | None = Field(default=None, description="命令生效后的当前目标点")
    nav_state: NavStateValue | None = Field(default=None, description="命令生效后的导航状态")
    received_at: datetime = Field(description="真实任务命令接收时间")
    detail: str = Field(description="真实任务执行链路返回的命令处理说明")


class NucMissionCommandResponse(ContractModel):
    success: bool = Field(default=True)
    data: NucMissionCommandResult


class CommandLogEntry(ContractModel):
    id: int = Field(description="自增日志 ID")
    command: str = Field(description="命令名称")
    source: str = Field(description="命令来源")
    requested_by: str | None = Field(default=None, description="命令发起人")
    payload: dict[str, JsonScalar] = Field(default_factory=dict, description="请求摘要")
    accepted: bool = Field(description="是否受理")
    detail: str = Field(description="处理结果说明")
    task_status: TaskStatus
    received_at: datetime = Field(description="命令接收时间")


class CommandLogsResponse(ContractModel):
    success: bool = Field(default=True)
    data: list[CommandLogEntry]
