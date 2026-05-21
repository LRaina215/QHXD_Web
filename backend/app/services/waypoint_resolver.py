import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WaypointResolveResult:
    waypoint_id: str | None
    name: str | None
    ambiguous: bool = False
    matches: list[dict[str, str]] = field(default_factory=list)


class WaypointResolver:
    """Resolves human waypoint aliases to stable waypoint IDs."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or Path(__file__).resolve().parents[1] / "config" / "waypoints.json"
        self._waypoints = self._load_waypoints()

    def resolve(self, text: str) -> tuple[str | None, str | None]:
        result = self.resolve_detail(text)
        if result.ambiguous:
            return None, None
        return result.waypoint_id, result.name

    def resolve_detail(self, text: str) -> WaypointResolveResult:
        normalized_text = self._normalize(text)
        candidates: list[dict[str, str | int]] = []
        for waypoint in self._waypoints:
            aliases = [waypoint["waypoint_id"], waypoint.get("name", ""), *waypoint.get("aliases", [])]
            best_alias = ""
            best_score = 0
            for alias in aliases:
                normalized_alias = self._normalize(str(alias))
                if normalized_alias and normalized_alias in normalized_text and len(normalized_alias) > best_score:
                    best_alias = str(alias)
                    best_score = len(normalized_alias)
            if best_score > 0:
                candidates.append({
                    "waypoint_id": str(waypoint["waypoint_id"]),
                    "name": str(waypoint.get("name", "")),
                    "alias": best_alias,
                    "score": best_score,
                })

        if not candidates:
            return WaypointResolveResult(None, None)

        best_score = max(int(item["score"]) for item in candidates)
        best_matches = [item for item in candidates if int(item["score"]) == best_score]
        match_payload = [
            {
                "waypoint_id": str(item["waypoint_id"]),
                "name": str(item["name"]),
                "alias": str(item["alias"]),
            }
            for item in best_matches
        ]
        unique_ids = {str(item["waypoint_id"]) for item in best_matches}
        if len(unique_ids) > 1:
            return WaypointResolveResult(None, None, ambiguous=True, matches=match_payload)

        best = best_matches[0]
        return WaypointResolveResult(str(best["waypoint_id"]), str(best["name"]), matches=match_payload)

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
