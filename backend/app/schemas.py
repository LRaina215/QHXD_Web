from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JsonScalar = str | int | float | bool | None

SystemModeValue = Literal["mock", "real"]
NavModeValue = Literal["auto", "manual"]
NavStateValue = Literal["idle", "running", "paused", "completed", "failed", "offline"]
TaskTypeValue = Literal["placeholder", "go_to_waypoint", "start_patrol", "return_home"]
TaskStateValue = Literal["idle", "pending", "running", "paused", "completed", "failed", "cancelled"]
SensorStatusValue = Literal["mock", "nominal", "warning", "fault", "offline"]
AlertLevelValue = Literal["info", "warning", "error", "critical"]
MissionCommandValue = Literal["go_to_waypoint", "start_patrol", "pause_task", "resume_task", "return_home"]
VoiceIntentValue = Literal[
    "go_to_waypoint",
    "start_patrol",
    "pause_task",
    "resume_task",
    "return_home",
    "query_status",
    "query_task",
    "query_detection",
    "query_self_identity",
    "query_capability",
    "query_safety_rule",
    "query_robot_status",
    "query_task_status",
    "query_battery",
    "query_emergency_stop",
    "query_perception_status",
    "query_weather",
    "query_environment",
    "speak_last_result",
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


class TaskStatus(ContractModel):
    task_id: str = Field(default="mock-task", description="任务 ID")
    task_type: TaskTypeValue = Field(default="placeholder", description="任务类型")
    state: TaskStateValue = Field(default="idle", description="任务状态")
    progress: int = Field(default=0, ge=0, le=100, description="任务进度，百分比")
    source: str = Field(default="web", description="任务来源")


class DeviceStatus(ContractModel):
    # Phase 3 映射约定：
    # real 模式下，device_status 应优先由 RT-Thread 底层状态经 NUC 归一化后提供，
    # RK3588 继续复用该公开契约，不新增平行字段。
    battery_percent: int | None = Field(default=100, ge=0, le=100, description="电量百分比")
    emergency_stop: bool = Field(default=False, description="急停状态")
    fault_code: str | None = Field(default=None, description="故障码")
    online: bool = Field(default=True, description="节点在线状态")


class EnvSensor(ContractModel):
    # Phase 3 映射约定：
    # 若真实环境传感器未就绪，允许 NUC 上送 null 值占位，并以 status 表示可用性。
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


class RobotState(ContractModel):
    robot_pose: RobotPose
    nav_status: NavStatus
    task_status: TaskStatus
    device_status: DeviceStatus
    env_sensor: EnvSensor
    system_mode: SystemMode
    detection_status: DetectionStatus | None = Field(default=None, description="可选本地视觉检测状态")
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
    humidity_percent: float | None = None
    weather: str
    wind: str | None = None
    source: str = Field(default="weather_provider")
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


class MissionActionResult(ContractModel):
    accepted: bool = Field(default=True)
    command: str = Field(description="命令名称")
    task_status: TaskStatus
    received_at: datetime = Field(description="命令接收时间")
    detail: str = Field(description="命令处理说明")


class MissionActionResponse(ContractModel):
    success: bool = Field(default=True)
    data: MissionActionResult


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
    detail: str | None = None
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
    # Phase 3 三节点映射约定：
    # - robot_pose / nav_status / task_status 主要来自 NUC 高层状态
    # - device_status / optional env_sensor 主要来自 RT-Thread，经 NUC 聚合后统一上送
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
    received_at: datetime = Field(description="NUC 状态接收时间")
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
    command: MissionCommandValue = Field(description="转发到 NUC 的命令名称")
    source: str = Field(default="web", description="命令来源")
    requested_by: str | None = Field(default=None, description="命令发起人")
    payload: dict[str, JsonScalar] = Field(default_factory=dict, description="命令参数")


class NucMissionCommandResult(ContractModel):
    accepted: bool = Field(description="NUC 是否已受理该命令")
    command: MissionCommandValue = Field(description="NUC 已处理的命令名称")
    task_status: TaskStatus
    current_goal: str | None = Field(default=None, description="命令生效后的当前目标点")
    nav_state: NavStateValue | None = Field(default=None, description="命令生效后的导航状态")
    received_at: datetime = Field(description="NUC 命令接收时间")
    detail: str = Field(description="NUC 返回的命令处理说明")


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
