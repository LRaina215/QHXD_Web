from datetime import datetime, timezone

from app.schemas import MissionExecutorUpdateRequest, MissionExecutorUpdateResult, RobotState
from app.services.mode_manager import mode_manager
from app.services.persistence import persistence
from app.services.state_store import state_store


class MissionUpdateService:
    def ingest(self, request: MissionExecutorUpdateRequest) -> tuple[MissionExecutorUpdateResult, RobotState | None]:
        if state_store.get_system_mode().mode != "real":
            return (
                MissionExecutorUpdateResult(
                    accepted=False,
                    state_updated=False,
                    detail="当前不是 Real 模式，已忽略 Nav2 任务状态。",
                ),
                None,
            )

        inserted = True
        if request.event.event_type != "progress":
            inserted = persistence.save_task_event(request.event)
        latest = state_store.get_latest_state()
        updated_at = request.task_status.updated_at or request.event.timestamp or datetime.now(timezone.utc)
        next_state = latest.model_copy(
            update={
                "task_status": request.task_status,
                "nav_status": latest.nav_status.model_copy(
                    update={
                        "state": request.nav_state,
                        "current_goal": request.current_goal,
                        "remaining_distance": request.event.remaining_distance,
                    }
                ),
                "updated_at": updated_at,
            }
        )
        published = state_store.publish_real_state(next_state)
        if published is not None:
            published = mode_manager.promote_real_command_feedback(published)
            persistence.save_state_snapshot(published)
        return (
            MissionExecutorUpdateResult(
                accepted=True,
                state_updated=published is not None,
                duplicate=not inserted,
                detail="Nav2 任务状态已更新。" if inserted else "重复任务事件已忽略，状态已同步。",
            ),
            published,
        )


mission_update_service = MissionUpdateService()
