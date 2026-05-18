from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSTACLE_CLASSES = {"chair", "backpack", "suitcase", "box", "bottle", "traffic cone", "obstacle"}


def build_detection_status(
    objects: list[dict[str, Any]],
    *,
    model_name: str,
    frame_id: str = "camera_front",
    source: str = "rk3588-rknn-yolo",
    enabled: bool = True,
    timestamp: str | None = None,
    blockage_frames: int = 0,
) -> dict[str, Any]:
    normalized_objects = [_normalize_object(item) for item in objects]
    events = _build_events(normalized_objects, blockage_frames)
    return {
        "enabled": enabled,
        "source": source,
        "model_name": Path(model_name).name,
        "frame_id": frame_id,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "objects": normalized_objects,
        "events": events,
    }


def _normalize_object(item: dict[str, Any]) -> dict[str, Any]:
    bbox = item.get("bbox_xyxy", [0, 0, 0, 0])
    return {
        "class_name": str(item.get("class_name", "unknown")),
        "confidence": float(item.get("confidence", 0.0)),
        "bbox_xyxy": [float(value) for value in bbox[:4]],
    }


def _build_events(objects: list[dict[str, Any]], blockage_frames: int) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    has_obstacle = False

    for item in objects:
        class_name = item["class_name"]
        if class_name == "person":
            events.append({
                "event_type": "person_detected",
                "level": "info",
                "message": "检测到人员目标",
            })
        elif class_name in OBSTACLE_CLASSES:
            has_obstacle = True
            events.append({
                "event_type": "obstacle_detected",
                "level": "warning",
                "message": f"检测到可能障碍物：{class_name}",
            })

    if has_obstacle and blockage_frames >= 3:
        events.append({
            "event_type": "possible_blockage",
            "level": "warning",
            "message": "障碍目标连续出现，可能存在通道阻塞",
        })

    return events
