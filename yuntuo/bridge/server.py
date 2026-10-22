"""fpga_bridge 进程入口：HTTP（仅本机 127.0.0.1:9101）+ 主循环。

  python -m yuntuo.fpga_bridge --link uart:/dev/ttyACM0                     实车（板载 USB 串口，方案 R0）
  python -m yuntuo.fpga_bridge --link udp:127.0.0.1:9000 --mock             配合 python -m yuntuo.mock_fpga

HTTP 接口（与原 nav2_mission_executor 相同的契约 + FPGA 专用接口）：
  GET  /health
  POST /api/internal/mission            {command, source, requested_by, payload}（后端 nav2_mission_adapter 调用）
  POST /api/internal/fpga/estop         {engage: true|false}
  POST /api/internal/fpga/set_pose      {x, y, yaw, align, range_m, range_deg}（m / rad，地图系）
  POST /api/internal/fpga/map           {path, map_id}（下发 .nvmp 先验地图）
  GET  /api/internal/fpga/status
"""
from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from yuntuo.bridge.config import BridgeConfig
from yuntuo.bridge.core import FpgaBridge
from yuntuo.bridge.inputs import PerceptionInbox, TelemetryReader

log = logging.getLogger("fpga_bridge")

POST_ROUTES = {
    "/api/internal/mission": "mission",
    "/api/internal/fpga/estop": "estop",
    "/api/internal/fpga/set_pose": "set_pose",
    "/api/internal/fpga/map": "map",
}


class Handler(BaseHTTPRequestHandler):
    bridge: FpgaBridge

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, self.bridge.snapshot() or {"status": "starting"})
        elif self.path == "/api/internal/fpga/status":
            snap = self.bridge.snapshot()
            self._json(200, {"success": True, "data": snap.get("platform")})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        kind = POST_ROUTES.get(self.path)
        if kind is None:
            self._json(404, {"error": "not_found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size).decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError
        except Exception:
            self._json(400, {"error": "invalid_json"})
            return
        response = self.bridge.submit(kind, payload)
        if response is None:
            self._json(504, {"error": "bridge_timeout"})
            return
        self._json(200, response)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> int:
    cfg = BridgeConfig.from_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--link", default=cfg.link)
    ap.add_argument("--mock", action="store_true", help="对端是 mock_fpga（网页标注为模拟）")
    ap.add_argument("--backend", default=cfg.backend_url)
    ap.add_argument("--port", type=int, default=cfg.http_port)
    ap.add_argument("--perception-udp", default=cfg.perception_udp, help="感知检测输入，空字符串关闭")
    ap.add_argument("--telemetry", default=cfg.telemetry, help="控制遥测：serial:/dev/ttyUSB0@230400 或 udp:HOST:PORT")
    ap.add_argument("--map", default=str(cfg.map_package) if cfg.map_package else None, help="启动时下发的 .nvmp")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg.link, cfg.backend_url, cfg.http_port = args.link, args.backend.rstrip("/"), args.port
    cfg.link_is_mock = cfg.link_is_mock or args.mock
    perception = PerceptionInbox(args.perception_udp) if args.perception_udp else None
    telemetry = TelemetryReader(args.telemetry) if args.telemetry else None
    bridge = FpgaBridge(cfg, perception=perception, telemetry=telemetry)
    for worker in (perception, telemetry, bridge.poster):
        if worker is not None:
            worker.start()
    if args.map:
        try:
            bridge.load_map_file(Path(args.map))
        except Exception as exc:
            log.error("先验地图 %s 不可用：%s", args.map, exc)
    Handler.bridge = bridge
    server = ThreadingHTTPServer((cfg.http_host, cfg.http_port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()
    log.info("fpga_bridge 就绪：链路 %s，HTTP %s:%d，后端 %s", cfg.link, cfg.http_host, cfg.http_port, cfg.backend_url)
    try:
        while True:
            if not bridge.tick():
                time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0
