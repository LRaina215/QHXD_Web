import math
from datetime import datetime, timezone

from app.schemas import (
    AlertEvent,
    DeviceStatus,
    EnvSensor,
    GoToWaypointRequest,
    MissionActionResult,
    MissionRequestBase,
    ModeSwitchRequest,
    ModeSwitchResult,
    NavStatus,
    PauseMissionRequest,
    ResumeMissionRequest,
    ReturnHomeRequest,
    RobotPose,
    RobotState,
    StartPatrolRequest,
    SystemMode,
    TaskStatus,
)
from app.services.persistence import persistence


class MockStateService:
    """Phase 1 mock state generator without real hardware dependencies."""

    def __init__(self) -> None:
        self._sequence = 0
        self._current_task = TaskStatus()
        self._system_mode = SystemMode(mode="mock", updated_at=self._timestamp())
        self._current_state = self._build_state()

    def initialize(self) -> None:
        persistence.initialize()
        startup_alert = AlertEvent(
            alert_id="alert-startup",
            level="info",
            message="Phase 1 mock middleware started.",
            source="rk3588-middleware",
            timestamp=self._timestamp(),
            acknowledged=False,
        )
        persistence.save_alert(startup_alert)
        self._current_state = self._build_state()
        persistence.save_state_snapshot(self._current_state)

    def tick(self) -> RobotState:
        self._sequence += 1
        self._advance_task()
        self._current_state = self._build_state()
        persistence.save_state_snapshot(self._current_state)

        alert = self._maybe_generate_alert()
        if alert is not None:
            persistence.save_alert(alert)

        return self.get_latest_state()

    def get_latest_state(self) -> RobotState:
        return self._current_state.model_copy(deep=True)

    def get_current_task(self) -> TaskStatus:
        return self._current_task.model_copy(deep=True)

    def get_system_mode(self) -> SystemMode:
        return self._system_mode.model_copy(deep=True)

    def get_alerts(self) -> list[AlertEvent]:
        return persistence.list_recent_alerts()

    def get_command_logs(self) -> list:
        return persistence.list_command_logs()

    def switch_system_mode(self, request: ModeSwitchRequest) -> ModeSwitchResult:
        self._system_mode = SystemMode(mode=request.mode, updated_at=self._timestamp())
        self._current_state = self._build_state()
        return ModeSwitchResult(
            accepted=True,
            system_mode=self.get_system_mode(),
            received_at=self._timestamp(),
            detail=(
                f"已切换到 {request.mode} 模式。"
                "当前阶段仅冻结契约，未接入真实 NUC 通信，状态仍由本地占位实现驱动。"
            ),
        )

    def go_to_waypoint(self, request: GoToWaypointRequest) -> MissionActionResult:
        self._current_task = TaskStatus(
            task_id="task-go-to-waypoint",
            task_type="go_to_waypoint",
            state="running",
            progress=10,
            source=request.source,
        )
        result = MissionActionResult(
            accepted=True,
            command="go_to_waypoint",
            task_status=self.get_current_task(),
            received_at=self._timestamp(),
            detail=f"已受理前往目标点 {request.waypoint_id} 的模拟命令。",
        )
        self._record_command(request, result, {"waypoint_id": request.waypoint_id})
        return result

    def start_patrol(self, request: StartPatrolRequest) -> MissionActionResult:
        self._current_task = TaskStatus(
            task_id="task-start-patrol",
            task_type="start_patrol",
            state="running",
            progress=5,
            source=request.source,
        )
        result = MissionActionResult(
            accepted=True,
            command="start_patrol",
            task_status=self.get_current_task(),
            received_at=self._timestamp(),
            detail=f"已受理巡检路线 {request.patrol_id} 的模拟命令。",
        )
        self._record_command(request, result, {"patrol_id": request.patrol_id})
        return result

    def pause(self, request: PauseMissionRequest) -> MissionActionResult:
        self._current_task = self._current_task.model_copy(
            update={"state": "paused", "source": request.source}
        )
        result = MissionActionResult(
            accepted=True,
            command="pause",
            task_status=self.get_current_task(),
            received_at=self._timestamp(),
            detail="已暂停当前模拟任务。",
        )
        self._record_command(request, result, {})
        return result

    def resume(self, request: ResumeMissionRequest) -> MissionActionResult:
        self._current_task = self._current_task.model_copy(
            update={"state": "running", "source": request.source}
        )
        result = MissionActionResult(
            accepted=True,
            command="resume",
            task_status=self.get_current_task(),
            received_at=self._timestamp(),
            detail="已恢复当前模拟任务。",
        )
        self._record_command(request, result, {})
        return result

    def return_home(self, request: ReturnHomeRequest) -> MissionActionResult:
        self._current_task = TaskStatus(
            task_id="task-return-home",
            task_type="return_home",
            state="running",
            progress=15,
            source=request.source,
        )
        result = MissionActionResult(
            accepted=True,
            command="return_home",
            task_status=self.get_current_task(),
            received_at=self._timestamp(),
            detail="已受理返航模拟命令。",
        )
        self._record_command(request, result, {})
        return result

    @staticmethod
    def _timestamp() -> datetime:
        return datetime.now(timezone.utc)

    def _build_state(self) -> RobotState:
        timestamp = self._timestamp()
        angle = self._sequence / 6.0
        progress = self._current_task.progress

        return RobotState(
            robot_pose=RobotPose(
                x=round(math.cos(angle) * 1.8, 3),
                y=round(math.sin(angle) * 1.2, 3),
                yaw=round(angle % (2 * math.pi), 3),
                frame_id="map",
                timestamp=timestamp,
            ),
            nav_status=NavStatus(
                mode="auto",
                state=self._nav_state(),
                current_goal=self._task_goal(),
                remaining_distance=self._remaining_distance(progress),
            ),
            task_status=self.get_current_task(),
            device_status=DeviceStatus(
                battery_percent=max(40, 100 - (self._sequence % 61)),
                emergency_stop=False,
                fault_code=None,
                online=True,
            ),
            env_sensor=EnvSensor(
                temperature_c=round(24.0 + math.sin(angle) * 2.0, 2),
                humidity_percent=round(46.0 + math.cos(angle) * 8.0, 2),
                status="mock",
            ),
            system_mode=self.get_system_mode(),
            updated_at=timestamp,
        )

    def _advance_task(self) -> None:
        if self._current_task.state != "running":
            return

        next_progress = min(self._current_task.progress + 5, 100)
        next_state = "completed" if next_progress >= 100 else "running"
        self._current_task = self._current_task.model_copy(
            update={"progress": next_progress, "state": next_state}
        )

    def _nav_state(self) -> str:
        if self._current_task.state == "running":
            return "running"
        if self._current_task.state == "paused":
            return "paused"
        return "idle"

    def _task_goal(self) -> str | None:
        if self._current_task.task_type == "go_to_waypoint":
            return "mock-waypoint"
        if self._current_task.task_type == "start_patrol":
            return "mock-patrol-route"
        if self._current_task.task_type == "return_home":
            return "home"
        return None

    @staticmethod
    def _remaining_distance(progress: int) -> float | None:
        if progress >= 100:
            return 0.0
        if progress <= 0:
            return None
        return round((100 - progress) * 0.2, 2)

    def _maybe_generate_alert(self) -> AlertEvent | None:
        if self._sequence > 0 and self._sequence % 15 == 0:
            return AlertEvent(
                alert_id=f"alert-mock-{self._sequence:04d}",
                level="info",
                message=f"模拟状态循环已运行 {self._sequence} 次。",
                source="mock-state-generator",
                timestamp=self._timestamp(),
                acknowledged=False,
            )
        return None

    def _record_command(
        self,
        request: MissionRequestBase,
        result: MissionActionResult,
        payload: dict[str, str | int | float | bool | None],
    ) -> None:
        persistence.save_command_log(
            command=result.command,
            source=request.source,
            requested_by=request.requested_by,
            payload=payload,
            result=result,
        )
        self._current_state = self._build_state()
        persistence.save_state_snapshot(self._current_state)


mock_state_service = MockStateService()
