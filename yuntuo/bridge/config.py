"""fpga_bridge 配置：环境变量（systemd EnvironmentFile）为主，命令行可覆盖。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass
class BridgeConfig:
    link: str = "udp:127.0.0.1:9000"           # uart:/dev/ttyACM0 | udp:192.168.2.100
    local_udp_port: int = 9001
    link_is_mock: bool = False                  # 对端是 mock_fpga：网页上标注"模拟"
    backend_url: str = "http://127.0.0.1:8000"
    http_host: str = "127.0.0.1"
    http_port: int = 9101
    perception_udp: str | None = "127.0.0.1:9102"
    telemetry: str | None = None                # nv (shared SFP) | serial:/dev/ttyUSB0@230400 | udp:127.0.0.1:9104
    waypoints_path: Path = ROOT / "backend/app/config/yuntuo/waypoints.json"
    routes_path: Path = ROOT / "backend/app/config/yuntuo/patrol_routes.json"
    map_package: Path | None = None             # 启动时下发的先验地图 .nvmp
    send_goal_yaw: bool = False                 # 固件 GOAL 末端朝向尚未启用，缺省发"不关心"
    allow_mapless_goto: bool = True             # 无图模式下点位按里程计系解释（原点 = 上电 / SET_POSE）
    require_localization: bool = True           # 有图时须 loc_state = 正常/退化 才能发运动任务
    target_rate_hz: float = 12.0
    target_max_latency_ms: int = 400
    target_arrive_tol_m: float = 0.25           # 跟踪站位点容差
    goto_arrive_tol_m: float = 0.15             # 当前估计位置，不代表独立真值精度
    target_arrive_dist_m: float = 1.05          # 判定"到达目标附近"的最大目标距离（站位 0.7 m + 余量）
    arrive_hold_s: float = 1.0
    blocked_fail_s: float = 25.0
    status_timeout_s: float = 1.5
    link_loss_fail_s: float = 10.0
    goal_confirm_s: float = 1.2
    nav_post_hz: float = 5.0
    platform_post_hz: float = 2.0
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        cfg = cls()
        cfg.link = _env("YUNTUO_FPGA_LINK", cfg.link)
        cfg.local_udp_port = int(_env("YUNTUO_FPGA_LOCAL_PORT", str(cfg.local_udp_port)))
        cfg.link_is_mock = _env_bool("YUNTUO_FPGA_IS_MOCK", cfg.link_is_mock)
        cfg.backend_url = _env("YUNTUO_BACKEND_URL", cfg.backend_url).rstrip("/")
        cfg.http_host = _env("YUNTUO_BRIDGE_HOST", cfg.http_host)
        cfg.http_port = int(_env("NAV_MISSION_EXECUTOR_PORT", str(cfg.http_port)))
        cfg.perception_udp = _env("YUNTUO_PERCEPTION_UDP", cfg.perception_udp or "") or None
        cfg.telemetry = _env("YUNTUO_CONTROL_TELEMETRY", "") or None
        cfg.waypoints_path = Path(_env("WAYPOINTS_CONFIG_PATH", str(cfg.waypoints_path)))
        cfg.routes_path = Path(_env("PATROL_ROUTES_CONFIG_PATH", str(cfg.routes_path)))
        map_pkg = _env("YUNTUO_PRIOR_MAP", "")
        cfg.map_package = Path(map_pkg) if map_pkg else None
        cfg.extra["map_id"] = _env("YUNTUO_MAP_ID", "yuntuo_field")
        bounds = _env("YUNTUO_FIELD_BOUNDS", "-1,-3,6,3")
        try:
            x0, y0, x1, y1 = (float(v) for v in bounds.split(","))
            cfg.extra["field_bounds"] = (x0, y0, x1, y1)
        except ValueError:
            pass
        cfg.send_goal_yaw = _env_bool("YUNTUO_SEND_GOAL_YAW", cfg.send_goal_yaw)
        cfg.allow_mapless_goto = _env_bool("YUNTUO_ALLOW_MAPLESS_GOTO", cfg.allow_mapless_goto)
        cfg.require_localization = _env_bool("YUNTUO_REQUIRE_LOCALIZATION", cfg.require_localization)
        cfg.target_rate_hz = _env_float("YUNTUO_TARGET_RATE_HZ", cfg.target_rate_hz)
        cfg.target_max_latency_ms = int(_env_float("YUNTUO_TARGET_MAX_LATENCY_MS", cfg.target_max_latency_ms))
        cfg.blocked_fail_s = _env_float("YUNTUO_BLOCKED_FAIL_SECONDS", cfg.blocked_fail_s)
        return cfg


@dataclass(frozen=True)
class Waypoint:
    waypoint_id: str
    name: str
    x: float
    y: float
    yaw: float


def load_waypoints(path: Path) -> dict[str, Waypoint]:
    items = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, Waypoint] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        pose = item.get("pose")
        if isinstance(pose, dict):
            pose = [pose.get("x"), pose.get("y"), pose.get("yaw", 0.0)]
        if not isinstance(pose, (list, tuple)) or len(pose) < 2 or pose[0] is None or pose[1] is None:
            continue
        wid = str(item["waypoint_id"])
        out[wid] = Waypoint(wid, str(item.get("name") or wid), float(pose[0]), float(pose[1]),
                            float(pose[2]) if len(pose) > 2 and pose[2] is not None else 0.0)
    return out


def load_routes(path: Path) -> dict[str, dict[str, Any]]:
    items = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["route_id"]): item for item in items if isinstance(item, dict)}
