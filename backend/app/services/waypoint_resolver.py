from dataclasses import dataclass, field

from app.services.waypoint_registry import waypoint_registry


@dataclass(frozen=True)
class WaypointResolveResult:
    waypoint_id: str | None
    name: str | None
    ambiguous: bool = False
    matches: list[dict[str, str]] = field(default_factory=list)


class WaypointResolver:
    """Resolves human waypoint aliases to stable waypoint IDs."""

    def resolve(self, text: str) -> tuple[str | None, str | None]:
        result = self.resolve_detail(text)
        if result.ambiguous:
            return None, None
        return result.waypoint_id, result.name

    def list_waypoints(self) -> list[dict[str, object]]:
        return [item.model_dump(mode="json") for item in waypoint_registry.list()]

    def waypoint_exists(self, waypoint_id: str | None) -> bool:
        if waypoint_id is None:
            return False
        return waypoint_registry.get(str(waypoint_id)) is not None

    def resolve_detail(self, text: str) -> WaypointResolveResult:
        normalized_text = self._normalize(text)
        candidates: list[dict[str, str | int]] = []
        for waypoint in waypoint_registry.list():
            aliases = [waypoint.waypoint_id, waypoint.name, *waypoint.aliases]
            best_alias = ""
            best_score = 0
            for alias in aliases:
                normalized_alias = self._normalize(str(alias))
                if normalized_alias and normalized_alias in normalized_text and len(normalized_alias) > best_score:
                    best_alias = str(alias)
                    best_score = len(normalized_alias)
            if best_score > 0:
                candidates.append({
                    "waypoint_id": waypoint.waypoint_id,
                    "name": waypoint.name,
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

    @staticmethod
    def _normalize(value: str) -> str:
        return waypoint_registry.normalize(value)


waypoint_resolver = WaypointResolver()
