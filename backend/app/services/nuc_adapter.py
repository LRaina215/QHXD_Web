import json
import os
from datetime import datetime, timezone
from urllib import error, request

from app.schemas import (
    JsonScalar,
    MissionActionResult,
    MissionCommandValue,
    NucMissionCommandRequest,
    NucMissionCommandResponse,
    NucStateUpdateRequest,
    NucStateUpdateResult,
    RobotState,
    TaskStatus,
)
from app.services.mode_manager import mode_manager
from app.services.persistence import persistence
from app.services.state_store import state_store


class NucAdapter:
    """Phase 2 adapter for NUC real-state ingest and mission forwarding."""

    def ingest_state_update(self, request: NucStateUpdateRequest) -> tuple[NucStateUpdateResult, RobotState | None]:
        current_mode = state_store.get_system_mode()
        received_at = self._timestamp()

        if current_mode.mode != "real":
            return (
                NucStateUpdateResult(
                    accepted=False,
                    system_mode=current_mode,
                    state_updated=False,
                    received_at=received_at,
                    detail="当前系统处于 mock 模式，已忽略 NUC 实时状态输入。",
                ),
                None,
            )

        next_state = RobotState(
            robot_pose=request.robot_pose,
            nav_status=request.nav_status,
            task_status=request.task_status,
            device_status=request.device_status,
            env_sensor=request.env_sensor,
            system_mode=current_mode,
            updated_at=request.updated_at,
        )
        latest_state = state_store.publish_real_state(next_state)

        if latest_state is not None:
            persistence.save_state_snapshot(latest_state)
        for alert in request.alerts:
            persistence.save_alert(alert)

        return (
            NucStateUpdateResult(
                accepted=True,
                system_mode=current_mode,
                state_updated=latest_state is not None,
                received_at=received_at,
                detail="已接收 NUC 实时状态并写入共享状态存储。",
            ),
            latest_state,
        )

    def forward_mission_command(
        self,
        command: MissionCommandValue,
        source: str,
        requested_by: str | None,
        payload: dict[str, JsonScalar],
    ) -> tuple[MissionActionResult, RobotState | None]:
        current_mode = state_store.get_system_mode()
        received_at = self._timestamp()

        if current_mode.mode != "real":
            return (
                MissionActionResult(
                    accepted=False,
                    command=self._public_command_name(command),
                    task_status=state_store.get_current_task(),
                    received_at=received_at,
                    detail="当前系统未处于 real 模式，未向 NUC 转发命令。",
                ),
                None,
            )

        command_request = NucMissionCommandRequest(
            command=command,
            source=source,
            requested_by=requested_by,
            payload=payload,
        )

        try:
            with self._build_opener().open(
                self._build_request(command_request),
                timeout=self._timeout_seconds(),
            ) as response:
                response_text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="ignore")
            error_detail = f"NUC 命令接口返回 HTTP {exc.code}：{response_text or '无响应正文'}"
            return (
                MissionActionResult(
                    accepted=False,
                    command=self._public_command_name(command),
                    task_status=state_store.get_current_task(),
                    received_at=received_at,
                    detail=error_detail,
                ),
                mode_manager.mark_real_bridge_error(error_detail),
            )
        except error.URLError as exc:
            error_detail = f"无法连接 NUC 命令接口：{exc.reason}"
            return (
                MissionActionResult(
                    accepted=False,
                    command=self._public_command_name(command),
                    task_status=state_store.get_current_task(),
                    received_at=received_at,
                    detail=error_detail,
                ),
                mode_manager.mark_real_bridge_error(error_detail),
            )
        except OSError as exc:
            error_detail = f"NUC 命令转发失败：{exc}"
            return (
                MissionActionResult(
                    accepted=False,
                    command=self._public_command_name(command),
                    task_status=state_store.get_current_task(),
                    received_at=received_at,
                    detail=error_detail,
                ),
                mode_manager.mark_real_bridge_error(error_detail),
            )

        try:
            parsed = NucMissionCommandResponse.model_validate(json.loads(response_text))
        except Exception as exc:
            error_detail = f"NUC 命令响应解析失败：{exc}"
            return (
                MissionActionResult(
                    accepted=False,
                    command=self._public_command_name(command),
                    task_status=state_store.get_current_task(),
                    received_at=received_at,
                    detail=error_detail,
                ),
                mode_manager.mark_real_bridge_error(error_detail),
            )

        result = MissionActionResult(
            accepted=parsed.data.accepted,
            command=self._public_command_name(command),
            task_status=parsed.data.task_status,
            received_at=parsed.data.received_at,
            detail=parsed.data.detail,
        )

        if not parsed.data.accepted:
            return result, None

        latest_state = self._apply_command_outcome(
            task_status=parsed.data.task_status,
            current_goal=parsed.data.current_goal,
            nav_state=parsed.data.nav_state,
        )
        return result, latest_state

    @staticmethod
    def _timestamp() -> datetime:
        return datetime.now(timezone.utc)

    def _apply_command_outcome(
        self,
        task_status: TaskStatus,
        current_goal: str | None,
        nav_state: str | None,
    ) -> RobotState | None:
        latest_state = state_store.get_latest_state()
        next_nav_state = nav_state or self._nav_state_from_task_state(task_status.state)
        next_state = latest_state.model_copy(
            update={
                "task_status": task_status,
                "nav_status": latest_state.nav_status.model_copy(
                    update={
                        "state": next_nav_state,
                        "current_goal": current_goal
                        if current_goal is not None
                        else latest_state.nav_status.current_goal,
                    }
                ),
                "updated_at": self._timestamp(),
            }
        )
        published_state = state_store.publish_real_state(next_state)
        if published_state is not None:
            published_state = mode_manager.promote_real_command_feedback(published_state)
        return published_state

    @staticmethod
    def _nav_state_from_task_state(task_state: str) -> str:
        if task_state == "running":
            return "running"
        if task_state == "paused":
            return "paused"
        if task_state == "completed":
            return "completed"
        if task_state == "failed":
            return "failed"
        return "idle"

    @staticmethod
    def _public_command_name(command: MissionCommandValue) -> str:
        if command == "pause_task":
            return "pause"
        if command == "resume_task":
            return "resume"
        return command

    @staticmethod
    def _build_opener():
        return request.build_opener(request.ProxyHandler({}))

    def _build_request(self, payload: NucMissionCommandRequest) -> request.Request:
        body = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
        return request.Request(
            url=f"{self._base_url()}{self._mission_path()}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    @staticmethod
    def _base_url() -> str:
        return os.getenv("NUC_BASE_URL", "http://127.0.0.1:9000").rstrip("/")

    @staticmethod
    def _mission_path() -> str:
        raw_path = os.getenv("NUC_MISSION_PATH", "/api/internal/rk3588/mission")
        return raw_path if raw_path.startswith("/") else f"/{raw_path}"

    @staticmethod
    def _timeout_seconds() -> float:
        try:
            return float(os.getenv("NUC_TIMEOUT_SECONDS", "2.0"))
        except ValueError:
            return 2.0


nuc_adapter = NucAdapter()
