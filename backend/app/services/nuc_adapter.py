from datetime import datetime, timezone

from app.schemas import NucStateUpdateRequest, NucStateUpdateResult, RobotState
from app.services.persistence import persistence
from app.services.state_store import state_store


class NucAdapter:
    """Phase 2 placeholder adapter that accepts real-state input from NUC."""

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

    @staticmethod
    def _timestamp() -> datetime:
        return datetime.now(timezone.utc)


nuc_adapter = NucAdapter()
