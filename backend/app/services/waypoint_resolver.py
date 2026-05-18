import json
from pathlib import Path


class WaypointResolver:
    """Resolves human waypoint aliases to stable waypoint IDs."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or Path(__file__).resolve().parents[1] / "config" / "waypoints.json"
        self._waypoints = self._load_waypoints()

    def resolve(self, text: str) -> tuple[str | None, str | None]:
        normalized_text = self._normalize(text)
        for waypoint in self._waypoints:
            aliases = [waypoint["waypoint_id"], waypoint.get("name", ""), *waypoint.get("aliases", [])]
            for alias in aliases:
                if alias and self._normalize(alias) in normalized_text:
                    return waypoint["waypoint_id"], waypoint.get("name")
        return None, None

    def _load_waypoints(self) -> list[dict[str, object]]:
        try:
            return json.loads(self._config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return [
                {
                    "waypoint_id": "wp_001",
                    "name": "一号点",
                    "aliases": ["一号点", "1号点", "一号", "201", "实验室", "送到实验室"],
                },
                {
                    "waypoint_id": "home",
                    "name": "起点",
                    "aliases": ["起点", "home", "家"],
                },
            ]

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(value.lower().split())


waypoint_resolver = WaypointResolver()
