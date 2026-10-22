import json
import os
from datetime import datetime, timezone
from urllib import error, request

from app.schemas import MissionActionResult, PlatformCommandResult, PlatformEstopRequest, PlatformSetPoseRequest
from app.services.persistence import persistence
from app.services.state_store import state_store


class PlatformAdapter:
    """急停 / 初始位姿：直接转给 fpga_bridge（与任务命令同一进程、同一端口）。"""

    def estop(self, req: PlatformEstopRequest) -> PlatformCommandResult:
        command = "estop" if req.engage else "estop_release"
        return self._forward(command, "/api/internal/fpga/estop", {"engage": req.engage}, req.source, req.requested_by)

    def set_pose(self, req: PlatformSetPoseRequest) -> PlatformCommandResult:
        payload = {"x": req.x, "y": req.y, "yaw": req.yaw, "align": req.align}
        return self._forward("set_pose", "/api/internal/fpga/set_pose", payload, req.source, req.requested_by)

    def _forward(self, command: str, path: str, payload: dict, source: str, requested_by: str | None):
        now = datetime.now(timezone.utc)
        if state_store.get_system_mode().mode != "real":
            result = PlatformCommandResult(accepted=False, command=command, received_at=now,
                                           detail="当前为 Mock 模式，没有真实 FPGA 可控制。")
        else:
            result = self._post(command, path, payload, now)
        log_entry = MissionActionResult(accepted=result.accepted, command=command, task_status=state_store.get_current_task(),
                                        received_at=result.received_at, detail=result.detail)
        persistence.save_command_log(command, source, requested_by, payload, log_entry)
        return result

    def _post(self, command: str, path: str, payload: dict, now: datetime) -> PlatformCommandResult:
        base = os.getenv("NAV_MISSION_EXECUTOR_BASE_URL", "http://127.0.0.1:9101").rstrip("/")
        req = request.Request(f"{base}{path}", data=json.dumps(payload).encode("utf-8"),
                              headers={"Content-Type": "application/json"}, method="POST")
        try:
            with request.build_opener(request.ProxyHandler({})).open(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8")).get("data") or {}
            return PlatformCommandResult(accepted=bool(data.get("accepted")), command=command, received_at=now,
                                         detail=str(data.get("detail") or "fpga_bridge 无说明"))
        except (error.URLError, OSError, ValueError) as exc:
            return PlatformCommandResult(accepted=False, command=command, received_at=now,
                                         detail=f"无法连接 fpga_bridge：{exc}")


platform_adapter = PlatformAdapter()
