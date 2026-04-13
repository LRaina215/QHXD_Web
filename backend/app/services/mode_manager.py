import os
from datetime import datetime, timezone

from app.schemas import AlertEvent, RobotState, SystemMode
from app.services.persistence import persistence
from app.services.state_store import state_store


class ModeManager:
    """Coordinates mock/real mode switching and real-link health state."""

    def __init__(self) -> None:
        self._last_real_update_at: datetime | None = None
        self._real_link_state = "unknown"

    def initialize(self, initial_state: RobotState) -> None:
        if initial_state.system_mode.mode == "real":
            self._last_real_update_at = initial_state.updated_at
            self._real_link_state = "online"
            return

        self._last_real_update_at = None
        self._real_link_state = "mock"

    def apply_mode_switch(self, system_mode: SystemMode, mock_state: RobotState) -> RobotState:
        base_state = state_store.switch_mode(system_mode)

        if system_mode.mode == "mock":
            self._last_real_update_at = None
            self._real_link_state = "mock"
            latest_state = state_store.publish_mock_state(mock_state) or base_state
            self._save_mode_alert("info", "已切换到 mock 模式，本地占位状态已恢复。")
            return latest_state

        self._last_real_update_at = None
        self._real_link_state = "waiting"
        waiting_state = self._build_real_status_state(
            base_state,
            nav_state="offline",
            sensor_status="offline",
            online=False,
            fault_code="waiting-for-real-state",
        )
        latest_state = state_store.publish_real_state(waiting_state) or base_state
        self._save_mode_alert("warning", "已切换到 real 模式，等待 NUC 实时状态上送。")
        return latest_state

    def record_real_state(self, state: RobotState) -> RobotState:
        previous_state = self._real_link_state
        self._last_real_update_at = state.updated_at
        self._real_link_state = "online"

        if previous_state in {"waiting", "timeout", "bridge_error"}:
            self._save_mode_alert("info", "NUC 实时状态链路已恢复。")

        return state

    def mark_real_bridge_error(self, detail: str) -> RobotState | None:
        if state_store.get_system_mode().mode != "real":
            return None

        latest_state = state_store.get_latest_state()
        self._real_link_state = "bridge_error"
        updated_state = self._build_real_status_state(
            latest_state,
            nav_state="offline",
            sensor_status="offline",
            online=False,
            fault_code="nuc-bridge-unreachable",
        )
        published_state = state_store.publish_real_state(updated_state)
        if published_state is None:
            return None

        persistence.save_state_snapshot(published_state)
        self._save_mode_alert("error", f"NUC bridge 异常：{detail}")
        return published_state

    def poll_real_health(self) -> RobotState | None:
        if state_store.get_system_mode().mode != "real":
            return None
        if self._last_real_update_at is None:
            return None

        latest_state = state_store.get_latest_state()
        elapsed_seconds = (self._timestamp() - self._last_real_update_at).total_seconds()
        if elapsed_seconds < self._real_stale_after_seconds():
            return None
        if self._real_link_state == "timeout":
            return None

        self._real_link_state = "timeout"
        updated_state = self._build_real_status_state(
            latest_state,
            nav_state="offline",
            sensor_status="offline",
            online=False,
            fault_code="nuc-state-timeout",
        )
        published_state = state_store.publish_real_state(updated_state)
        if published_state is None:
            return None

        persistence.save_state_snapshot(published_state)
        self._save_mode_alert("warning", "NUC 实时状态超时，已标记为离线。")
        return published_state

    def promote_real_command_feedback(self, state: RobotState) -> RobotState:
        if state.system_mode.mode != "real":
            return state

        previous_state = self._real_link_state
        self._real_link_state = "online"
        updated_state = state.model_copy(
            update={
                "device_status": state.device_status.model_copy(
                    update={
                        "online": True,
                        "fault_code": self._normalized_fault_code(state.device_status.fault_code),
                    }
                ),
                "updated_at": self._timestamp(),
            }
        )
        self._last_real_update_at = updated_state.updated_at
        published_state = state_store.publish_real_state(updated_state)
        if published_state is None:
            return state

        if previous_state in {"timeout", "bridge_error"}:
            self._save_mode_alert("info", "NUC 任务桥链路已恢复。")
        persistence.save_state_snapshot(published_state)
        return published_state

    @staticmethod
    def _build_real_status_state(
        state: RobotState,
        *,
        nav_state: str,
        sensor_status: str,
        online: bool,
        fault_code: str,
    ) -> RobotState:
        return state.model_copy(
            update={
                "nav_status": state.nav_status.model_copy(update={"state": nav_state}),
                "device_status": state.device_status.model_copy(
                    update={
                        "online": online,
                        "fault_code": fault_code,
                    }
                ),
                "env_sensor": state.env_sensor.model_copy(update={"status": sensor_status}),
                "updated_at": ModeManager._timestamp(),
            }
        )

    def _save_mode_alert(self, level: str, message: str) -> None:
        persistence.save_alert(
            AlertEvent(
                alert_id=f"mode-manager-{self._timestamp().strftime('%Y%m%d%H%M%S%f')}",
                level=level,
                message=message,
                source="mode-manager",
                timestamp=self._timestamp(),
                acknowledged=False,
            )
        )

    @staticmethod
    def _normalized_fault_code(current_fault_code: str | None) -> str | None:
        if current_fault_code in {
            None,
            "waiting-for-real-state",
            "nuc-state-timeout",
            "nuc-bridge-unreachable",
        }:
            return None
        return current_fault_code

    @staticmethod
    def _timestamp() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _real_stale_after_seconds() -> float:
        try:
            return float(os.getenv("REAL_STATE_STALE_AFTER_SECONDS", "5.0"))
        except ValueError:
            return 5.0


mode_manager = ModeManager()
