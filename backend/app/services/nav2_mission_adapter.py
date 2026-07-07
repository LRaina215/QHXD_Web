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
    RobotState,
    TaskStatus,
)
from app.services.mode_manager import mode_manager
from app.services.state_store import state_store


class Nav2MissionAdapter:
    """Loopback client for the independent ROS 2 Nav2 mission executor."""

    def forward(
        self,
        command: MissionCommandValue,
        source: str,
        requested_by: str | None,
        payload: dict[str, JsonScalar],
    ) -> tuple[MissionActionResult, RobotState | None]:
        received_at = datetime.now(timezone.utc)
        if state_store.get_system_mode().mode != "real":
            return self._rejected(command, "当前系统未处于 Real 模式，未发送 Nav2 任务。", received_at), None

        command_request = NucMissionCommandRequest(
            command=command,
            source=source,
            requested_by=requested_by,
            payload=payload,
        )
        try:
            body = json.dumps(command_request.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
            http_request = request.Request(
                url=f"{self._base_url()}{self._mission_path()}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.build_opener(request.ProxyHandler({})).open(
                http_request, timeout=self._timeout_seconds()
            ) as response:
                response_text = response.read().decode("utf-8")
            parsed = NucMissionCommandResponse.model_validate(json.loads(response_text))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            return self._failure(command, f"Nav2 任务执行器返回 HTTP {exc.code}：{detail or '无响应正文'}")
        except (error.URLError, OSError) as exc:
            return self._failure(command, f"无法连接 Nav2 任务执行器：{exc}")
        except Exception as exc:
            return self._failure(command, f"Nav2 任务执行器响应无效：{exc}")

        result = MissionActionResult(
            accepted=parsed.data.accepted,
            command=self._public_command_name(command),
            task_status=parsed.data.task_status,
            received_at=parsed.data.received_at,
            detail=parsed.data.detail,
        )
        if not result.accepted:
            return result, None
        return result, self._apply_command_outcome(
            task_status=parsed.data.task_status,
            current_goal=parsed.data.current_goal,
            nav_state=parsed.data.nav_state,
        )

    def _failure(self, command: MissionCommandValue, detail: str):
        result = self._rejected(command, detail, datetime.now(timezone.utc))
        return result, mode_manager.mark_real_bridge_error(detail)

    @staticmethod
    def _rejected(command: MissionCommandValue, detail: str, received_at: datetime) -> MissionActionResult:
        return MissionActionResult(
            accepted=False,
            command=Nav2MissionAdapter._public_command_name(command),
            task_status=state_store.get_current_task(),
            received_at=received_at,
            detail=detail,
        )

    @staticmethod
    def _apply_command_outcome(
        task_status: TaskStatus,
        current_goal: str | None,
        nav_state: str | None,
    ) -> RobotState | None:
        latest = state_store.get_latest_state()
        next_state = latest.model_copy(
            update={
                "task_status": task_status,
                "nav_status": latest.nav_status.model_copy(
                    update={
                        "state": nav_state or "idle",
                        "current_goal": current_goal,
                    }
                ),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        published = state_store.publish_real_state(next_state)
        return mode_manager.promote_real_command_feedback(published) if published is not None else None

    @staticmethod
    def _public_command_name(command: MissionCommandValue) -> str:
        return {"pause_task": "pause", "resume_task": "resume", "cancel_task": "cancel"}.get(command, command)

    @staticmethod
    def _base_url() -> str:
        return os.getenv("NAV_MISSION_EXECUTOR_BASE_URL", "http://127.0.0.1:9101").rstrip("/")

    @staticmethod
    def _mission_path() -> str:
        path = os.getenv("NAV_MISSION_EXECUTOR_PATH", "/api/internal/mission")
        return path if path.startswith("/") else f"/{path}"

    @staticmethod
    def _timeout_seconds() -> float:
        try:
            return max(0.2, min(float(os.getenv("NAV_MISSION_EXECUTOR_TIMEOUT_SECONDS", "4")), 10.0))
        except ValueError:
            return 4.0


nav2_mission_adapter = Nav2MissionAdapter()
