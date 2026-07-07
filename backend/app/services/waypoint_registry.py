from __future__ import annotations

import json
import math
import os
from pathlib import Path

from app.schemas import WaypointDefinition, WaypointPose


class WaypointRegistry:
    """Validated, reload-on-change waypoint resource shared by voice and missions."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._explicit_path = config_path
        self._cached_path: Path | None = None
        self._cached_mtime_ns: int | None = None
        self._cached: list[WaypointDefinition] = []

    def list(self) -> list[WaypointDefinition]:
        self._reload_if_needed()
        return [item.model_copy(deep=True) for item in self._cached]

    def get(self, waypoint_id: str) -> WaypointDefinition | None:
        normalized = waypoint_id.strip()
        return next((item for item in self.list() if item.waypoint_id == normalized), None)

    def require_navigation_target(self, waypoint_id: str) -> WaypointDefinition:
        waypoint = self.get(waypoint_id)
        if waypoint is None:
            raise ValueError(f"目标点不存在：{waypoint_id}")
        if not waypoint.enabled:
            raise ValueError(f"目标点已禁用：{waypoint.name}")
        if waypoint.pose is None:
            raise ValueError(f"目标点尚未配置地图坐标：{waypoint.name} ({waypoint.waypoint_id})")
        return waypoint

    def validate(self) -> list[WaypointDefinition]:
        self._cached_mtime_ns = None
        return self.list()

    def _reload_if_needed(self) -> None:
        path = self._config_path()
        stat = path.stat()
        if path == self._cached_path and stat.st_mtime_ns == self._cached_mtime_ns:
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not payload:
            raise ValueError(f"waypoints 配置必须是非空数组：{path}")

        parsed: list[WaypointDefinition] = []
        seen_ids: set[str] = set()
        alias_owner: dict[str, str] = {}
        for index, raw in enumerate(payload):
            if not isinstance(raw, dict):
                raise ValueError(f"waypoints[{index}] 必须是对象")
            waypoint_id = str(raw.get("waypoint_id", "")).strip()
            name = str(raw.get("name", "")).strip()
            if not waypoint_id or not name:
                raise ValueError(f"waypoints[{index}] 缺少 waypoint_id 或 name")
            if waypoint_id in seen_ids:
                raise ValueError(f"重复 waypoint_id：{waypoint_id}")
            seen_ids.add(waypoint_id)

            aliases = [str(value).strip() for value in raw.get("aliases", []) if str(value).strip()]
            for alias in [waypoint_id, name, *aliases]:
                normalized = self.normalize(alias)
                owner = alias_owner.get(normalized)
                if owner is not None and owner != waypoint_id:
                    raise ValueError(f"点位别名冲突：{alias} 同时属于 {owner} 与 {waypoint_id}")
                alias_owner[normalized] = waypoint_id

            pose_payload = raw.get("pose")
            pose = None
            if pose_payload is not None:
                pose_payload = self._normalize_pose_payload(pose_payload, waypoint_id)
                pose = WaypointPose.model_validate(pose_payload)
                if not all(math.isfinite(value) for value in (pose.x, pose.y, pose.yaw)):
                    raise ValueError(f"目标点坐标不是有限数值：{waypoint_id}")

            parsed.append(
                WaypointDefinition(
                    waypoint_id=waypoint_id,
                    name=name,
                    aliases=aliases,
                    map_id=str(raw.get("map_id", "sentinel_map")).strip() or "sentinel_map",
                    pose=pose,
                    group=str(raw.get("group", "navigation")).strip() or "navigation",
                    enabled=bool(raw.get("enabled", True)),
                    configured=pose is not None,
                )
            )

        self._cached_path = path
        self._cached_mtime_ns = stat.st_mtime_ns
        self._cached = parsed

    def _config_path(self) -> Path:
        if self._explicit_path is not None:
            return self._explicit_path
        configured = os.getenv("WAYPOINTS_CONFIG_PATH")
        if configured:
            return Path(configured).expanduser()
        return Path(__file__).resolve().parents[1] / "config" / "waypoints.json"

    @staticmethod
    def normalize(value: str) -> str:
        return "".join(value.lower().split())

    @staticmethod
    def _normalize_pose_payload(payload, waypoint_id: str):
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list | tuple) and len(payload) >= 2:
            return {
                "x": payload[0],
                "y": payload[1],
                "yaw": payload[2] if len(payload) >= 3 else 0.0,
            }
        raise ValueError(f"目标点 pose 必须是对象或 [x, y, yaw] 数组：{waypoint_id}")


waypoint_registry = WaypointRegistry()
