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


class RobotState(ContractModel):
    robot_pose: RobotPose
    nav_status: NavStatus
    task_status: TaskStatus
    device_status: DeviceStatus
    env_sensor: EnvSensor
    system_mode: SystemMode
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


class ImuSample(ContractModel):
    frame_id: str = Field(description="IMU 坐标系")
    timestamp: datetime = Field(description="IMU 样本时间")
    orientation: QuaternionSample
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
