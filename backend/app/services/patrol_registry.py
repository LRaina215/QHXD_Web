import json
import os
from pathlib import Path

from app.services.waypoint_registry import waypoint_registry


class PatrolRegistry:
    def list(self) -> list[dict[str, object]]:
        path = self._config_path()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"巡检路线配置必须是数组：{path}")
        seen: set[str] = set()
        routes: list[dict[str, object]] = []
        for raw in payload:
            route_id = str(raw.get("route_id", "")).strip()
            points = [str(value) for value in raw.get("waypoints", [])]
            if not route_id or route_id in seen or not points:
                raise ValueError(f"巡检路线 ID 重复、为空或无点位：{route_id or '<empty>'}")
            seen.add(route_id)
            for waypoint_id in points:
                waypoint_registry.require_navigation_target(waypoint_id)
            if bool(raw.get("return_home", False)):
                waypoint_registry.require_navigation_target("home")
            routes.append(dict(raw))
        return routes

    def require(self, route_id: str) -> dict[str, object]:
        route = next((item for item in self.list() if item.get("route_id") == route_id), None)
        if route is None:
            raise ValueError(f"巡检路线不存在：{route_id}")
        if not bool(route.get("enabled", True)):
            raise ValueError(f"巡检路线已禁用：{route_id}")
        return route

    @staticmethod
    def _config_path() -> Path:
        configured = os.getenv("PATROL_ROUTES_CONFIG_PATH")
        if configured:
            return Path(configured).expanduser()
        return Path(__file__).resolve().parents[1] / "config" / "patrol_routes.json"


patrol_registry = PatrolRegistry()
