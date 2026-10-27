"""Browser bytes -> validated RK-local file -> existing FPGA bridge queue."""
import json
import os
import re
import sys
import threading
from pathlib import Path
from urllib import error, request
from uuid import uuid4

from fastapi import HTTPException

from app.services.state_store import state_store
# The documented backend launcher runs from backend/. Reuse the project's
# single FPGA package parser rather than keeping a second format definition.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from yuntuo.fpga_link.nvmp import MapPackageError, parse_package

MAX_MAP_BYTES = 48 + 5 * 16384 + 64 * 64
MAP_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")


class MapUploadService:
    def __init__(self):
        self.lock = threading.Lock()

    def _bridge(self, path: str, payload: dict | None = None) -> dict:
        base = os.getenv("NAV_MISSION_EXECUTOR_BASE_URL", "http://127.0.0.1:9101").rstrip("/")
        req = request.Request(base + path,
                              data=json.dumps(payload).encode() if payload is not None else None,
                              headers={"Content-Type": "application/json"} if payload is not None else {})
        try:
            with request.build_opener(request.ProxyHandler({})).open(req, timeout=3) as resp:
                return json.loads(resp.read())
        except (error.URLError, OSError, ValueError) as exc:
            raise HTTPException(503, "无法连接地图桥接服务，请检查机器人连接。") from exc

    def submit(self, data: bytes, filename: str, map_id: str) -> dict:
        if (not filename or len(filename) > 120 or "\x00" in filename
                or "/" in filename or "\\" in filename or not filename.lower().endswith(".nvmp")):
            raise HTTPException(422, "请选择有效的 .nvmp 地图文件。")
        if not MAP_ID.fullmatch(map_id):
            raise HTTPException(422, "地图ID只能包含1至64个字母、数字、下划线、短横线或点。")
        if len(data) > MAX_MAP_BYTES:
            raise HTTPException(413, "地图包超过当前FPGA容量（最大86064字节）。")
        try:
            parse_package(data)
        except MapPackageError as exc:
            raise HTTPException(422, str(exc)) from exc
        if state_store.get_system_mode().mode != "real":
            raise HTTPException(409, "当前为模拟模式；请切换真实机器人后上传地图。")
        if not self.lock.acquire(blocking=False):
            raise HTTPException(409, "另一份地图正在提交，请稍后再试。")
        try:
            folder = Path(os.getenv("YUNTUO_MAP_UPLOAD_DIR", str(Path(__file__).resolve().parents[2] / "data/prior_maps")))
            folder.mkdir(parents=True, exist_ok=True)
            upload_id = uuid4().hex
            path = folder / f"{upload_id}.nvmp"
            with path.open("xb") as handle:
                handle.write(data)
            try:
                response = self._bridge("/api/internal/fpga/map", {"path": str(path.resolve()),
                                        "map_id": map_id, "filename": filename, "upload_id": upload_id})
            except HTTPException:
                # An HTTP timeout can have an unknown queue outcome; keep the file.
                self._prune(folder, path)
                raise
            result = response.get("data") or {}
            if not result.get("accepted"):
                path.unlink(missing_ok=True)
                raise HTTPException(409, str(result.get("detail") or "机器人未接受地图。"))
            upload = result.get("upload")
            if not isinstance(upload, dict) or upload.get("id") != upload_id:
                raise HTTPException(502, "地图桥接版本不匹配，请更新服务后重试。")
            self._prune(folder, path)
            return {"success": True, "data": upload}
        finally:
            self.lock.release()

    @staticmethod
    def _prune(folder: Path, current: Path) -> None:
        # Only generated files in this directory; never remove a supplied path.
        files = sorted((p for p in folder.glob("*.nvmp") if re.fullmatch(r"[0-9a-f]{32}\.nvmp", p.name)),
                       key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for old in files[5:]:
            if old != current:
                old.unlink(missing_ok=True)

    def status(self) -> dict:
        if state_store.get_system_mode().mode != "real":
            return {"success": True, "data": {"state": "unavailable", "detail": "模拟模式不下发真实地图。"}}
        try:
            health = self._bridge("/health")
        except HTTPException as exc:
            return {"success": True, "data": {"state": "unavailable", "detail": exc.detail}}
        upload = health.get("map_upload")
        return {"success": True, "data": upload or {"state": "idle", "detail": "尚未通过网页上传地图。"}}


map_upload_service = MapUploadService()
