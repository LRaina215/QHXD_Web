from __future__ import annotations

import os
from datetime import datetime, timezone

from app.schemas import DetectionObject, DetectionStatus, VisualEventRecord
from app.services.persistence import persistence
from app.services.state_store import state_store


OBSTACLE_CLASSES = {"chair", "backpack", "suitcase", "box", "bottle", "traffic cone", "obstacle"}


class VisualEventService:
    """Persist coarse visual events without writing every YOLO frame."""

    def __init__(self) -> None:
        self._camera_offline = False

    def ingest_detection_status(self, detection: DetectionStatus) -> list[VisualEventRecord]:
        timestamp = detection.timestamp or datetime.now(timezone.utc)
        context = self._task_context()
        saved: list[VisualEventRecord] = []

        event_types = {event.event_type for event in detection.events}
        camera_unavailable = (not detection.enabled) or "camera_unavailable" in event_types or "camera_offline" in event_types
        if camera_unavailable:
            self._camera_offline = True
            saved.append(
                persistence.upsert_visual_event(
                    event_type="camera_offline",
                    level="warning",
                    class_name=None,
                    message="摄像头不可用或无法打开。",
                    source=detection.source,
                    task_id=context["task_id"],
                    waypoint_id=context["waypoint_id"],
                    timestamp=timestamp,
                    max_confidence=None,
                    time_window_seconds=self._event_window_seconds(),
                )
            )
            return saved

        if self._camera_offline:
            self._camera_offline = False
            saved.append(
                persistence.upsert_visual_event(
                    event_type="camera_recovered",
                    level="info",
                    class_name=None,
                    message="摄像头画面已恢复。",
                    source=detection.source,
                    task_id=context["task_id"],
                    waypoint_id=context["waypoint_id"],
                    timestamp=timestamp,
                    max_confidence=None,
                    time_window_seconds=self._event_window_seconds(),
                )
            )

        people = [obj for obj in detection.objects if obj.class_name == "person"]
        if people:
            best = self._best_object(people)
            saved.append(
                persistence.upsert_visual_event(
                    event_type="person_detected",
                    level="info",
                    class_name="person",
                    message="前方视觉检测到人员目标。",
                    source=detection.source,
                    task_id=context["task_id"],
                    waypoint_id=context["waypoint_id"],
                    timestamp=timestamp,
                    max_confidence=best.confidence,
                    time_window_seconds=self._event_window_seconds(),
                )
            )

        obstacles = [obj for obj in detection.objects if obj.class_name in OBSTACLE_CLASSES]
        if obstacles:
            classes = sorted({obj.class_name for obj in obstacles})
            best = self._best_object(obstacles)
            saved.append(
                persistence.upsert_visual_event(
                    event_type="obstacle_detected",
                    level="warning",
                    class_name=",".join(classes),
                    message=f"前方视觉检测到可能障碍物：{'、'.join(classes)}。",
                    source=detection.source,
                    task_id=context["task_id"],
                    waypoint_id=context["waypoint_id"],
                    timestamp=timestamp,
                    max_confidence=best.confidence,
                    time_window_seconds=self._event_window_seconds(),
                )
            )

        return saved

    def list_recent(
        self,
        limit: int = 20,
        event_type: str | None = None,
        task_id: str | None = None,
    ) -> list[VisualEventRecord]:
        return persistence.list_visual_events(limit=limit, event_type=event_type, task_id=task_id)

    @staticmethod
    def _best_object(objects: list[DetectionObject]) -> DetectionObject:
        return max(objects, key=lambda item: item.confidence)

    @staticmethod
    def _task_context() -> dict[str, str | None]:
        task = state_store.get_current_task()
        return {
            "task_id": None if task.task_id == "mock-task" else task.task_id,
            "waypoint_id": task.current_waypoint_id,
        }

    @staticmethod
    def _event_window_seconds() -> float:
        try:
            return max(1.0, float(os.getenv("VISUAL_EVENT_DEDUP_WINDOW_SECONDS", "8")))
        except ValueError:
            return 8.0


visual_event_service = VisualEventService()
