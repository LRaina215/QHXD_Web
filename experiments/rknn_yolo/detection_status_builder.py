from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSTACLE_CLASSES = {"chair", "backpack", "suitcase", "box", "bottle", "traffic cone", "obstacle"}


def build_detection_status(
    objects: list[dict[str, Any]],
    *,
    model_name: str,
    frame_id: str = "camera_front",
    source: str = "rk3588-rknn-yolo26",
    enabled: bool = True,
    timestamp: str | None = None,
    blockage_frames: int = 0,
    blockage_frames_required: int = 3,
    event_min_confidence: float = 0.0,
    event_min_area_ratio: float = 0.0,
    image_width: int | None = None,
    image_height: int | None = None,
) -> dict[str, Any]:
    normalized_objects = [_normalize_object(item) for item in objects]
    events = _build_events(
        normalized_objects,
        blockage_frames,
        blockage_frames_required,
        event_min_confidence,
        event_min_area_ratio,
        image_width,
        image_height,
    )
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
    normalized: dict[str, Any] = {
        "class_name": str(item.get("class_name", "unknown")),
        "confidence": float(item.get("confidence", 0.0)),
        "bbox_xyxy": [float(value) for value in bbox[:4]],
    }
    if "current_frame" in item:
        normalized["current_frame"] = bool(item["current_frame"])
    if "recently_seen" in item:
        normalized["recently_seen"] = bool(item["recently_seen"])
    if item.get("last_seen_at") is not None:
        normalized["last_seen_at"] = str(item["last_seen_at"])
    if item.get("age_s") is not None:
        normalized["age_s"] = round(float(item["age_s"]), 3)
    return normalized


def _build_events(
    objects: list[dict[str, Any]],
    blockage_frames: int,
    blockage_frames_required: int,
    event_min_confidence: float,
    event_min_area_ratio: float,
    image_width: int | None,
    image_height: int | None,
) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    event_objects = [
        item for item in objects
        if _passes_event_policy(item, event_min_confidence, event_min_area_ratio, image_width, image_height)
    ]
    current_objects = [item for item in event_objects if item.get("current_frame", True)]
    recent_objects = [item for item in event_objects if item.get("recently_seen", False) and not item.get("current_frame", True)]

    has_current_person = any(item["class_name"] == "person" for item in current_objects)
    has_recent_person = any(item["class_name"] == "person" for item in recent_objects)
    current_obstacles = sorted({item["class_name"] for item in current_objects if item["class_name"] in OBSTACLE_CLASSES})
    recent_obstacles = sorted({item["class_name"] for item in recent_objects if item["class_name"] in OBSTACLE_CLASSES})

    if has_current_person:
        events.append({
            "event_type": "person_detected",
            "level": "info",
            "message": "当前帧检测到人员目标",
        })
    elif has_recent_person:
        events.append({
            "event_type": "person_detected",
            "level": "info",
            "message": "最近检测到人员目标（短时保持）",
        })

    if current_obstacles:
        events.append({
            "event_type": "obstacle_detected",
            "level": "warning",
            "message": f"当前帧检测到可能障碍物：{', '.join(current_obstacles)}",
        })
    elif recent_obstacles:
        events.append({
            "event_type": "obstacle_detected",
            "level": "warning",
            "message": f"最近检测到可能障碍物（短时保持）：{', '.join(recent_obstacles)}",
        })

    if current_obstacles and blockage_frames >= max(1, blockage_frames_required):
        events.append({
            "event_type": "possible_blockage",
            "level": "warning",
            "message": f"障碍目标连续出现 {blockage_frames} 帧，可能存在通道阻塞",
        })

    return events


def _passes_event_policy(
    item: dict[str, Any],
    min_confidence: float,
    min_area_ratio: float,
    image_width: int | None,
    image_height: int | None,
) -> bool:
    if float(item.get("confidence", 0.0)) < min_confidence:
        return False
    if item.get("class_name") in OBSTACLE_CLASSES and min_area_ratio > 0:
        return _bbox_area_ratio(item.get("bbox_xyxy", []), image_width, image_height) >= min_area_ratio
    return True


def _bbox_area_ratio(bbox: list[float], image_width: int | None, image_height: int | None) -> float:
    if not image_width or not image_height or len(bbox) < 4:
        return 1.0
    x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    frame_area = float(image_width * image_height)
    return area / frame_area if frame_area > 0 else 0.0
