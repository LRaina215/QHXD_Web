#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import request
from uuid import uuid4

import rclpy
from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node


ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CommandRequest:
    payload: dict[str, Any]
    ready: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None


class MissionExecutor(Node):
    def __init__(self) -> None:
        super().__init__("qhxd_nav2_mission_executor")
        self._action_callback_group = ReentrantCallbackGroup()
        self._action = ActionClient(
            self,
            NavigateToPose,
            "navigate_to_pose",
            callback_group=self._action_callback_group,
        )
        self._commands: queue.Queue[CommandRequest] = queue.Queue(maxsize=16)
        self._updates: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=32)
        self._waypoints = self._load_waypoints()
        self._routes = self._load_routes()
        self._context: dict[str, Any] | None = None
        self._goal_handle = None
        self._cancel_mode: str | None = None
        self._cancel_request: CommandRequest | None = None
        self._feedback_sequence = 0
        self._last_feedback_at = 0.0
        self._initial_distance: float | None = None
        self._next_goal_due: float | None = None
        self.create_timer(0.2, self._process)
        self._update_worker = threading.Thread(target=self._post_updates, daemon=True)
        self._update_worker.start()
        self.get_logger().info(
            f"QHXD Nav2 mission executor ready: waypoints={len(self._waypoints)} "
            f"routes={len(self._routes)} action=navigate_to_pose"
        )

    def enqueue(self, command: CommandRequest) -> bool:
        try:
            self._commands.put_nowait(command)
            return True
        except queue.Full:
            return False

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "qhxd-nav2-mission-executor",
            "action_server_ready": self._action.server_is_ready(),
            "active_task": self._task_status() if self._context else None,
            "updated_at": utc_now(),
        }

    def _process(self) -> None:
        if self._next_goal_due is not None and time.monotonic() >= self._next_goal_due:
            self._next_goal_due = None
            if self._context and self._context["state"] == "running":
                self._send_current_goal(None)
        try:
            command = self._commands.get_nowait()
        except queue.Empty:
            return
        self._handle_command(command)

    def _handle_command(self, pending: CommandRequest) -> None:
        payload = pending.payload
        command = str(payload.get("command", ""))
        args = payload.get("payload") or {}
        source = str(payload.get("source") or "web")

        if command in {"pause_task", "cancel_task"}:
            self._cancel_active(command, pending)
            return
        if command == "resume_task":
            self._resume(pending)
            return
        if command not in {"go_to_waypoint", "return_home", "start_patrol"}:
            self._reply(pending, False, command, f"不支持的任务命令：{command}")
            return
        if self._context and self._context.get("state") in {"pending", "running", "paused"}:
            self._reply(pending, False, command, "已有活动任务，请先取消当前任务。")
            return
        if not self._action.server_is_ready():
            self._reply(pending, False, command, "Nav2 NavigateToPose Action Server 未就绪。")
            return

        try:
            if command == "go_to_waypoint":
                point_ids = [str(args["waypoint_id"])]
                task_type = "go_to_waypoint"
            elif command == "return_home":
                point_ids = ["home"]
                task_type = "return_home"
            else:
                route_id = str(args.get("patrol_id", "default_patrol"))
                route = self._routes.get(route_id)
                if not route or not route.get("enabled", True):
                    raise ValueError(f"巡检路线不存在或已禁用：{route_id}")
                point_ids = list(route["waypoints"])
                if route.get("return_home"):
                    point_ids.append("home")
                task_type = "start_patrol"
                args["route_id"] = route_id
            for waypoint_id in point_ids:
                self._require_waypoint(waypoint_id)
        except (KeyError, ValueError) as exc:
            self._reply(pending, False, command, str(exc))
            return

        task_id = f"nav2-{task_type}-{uuid4().hex[:12]}"
        self._context = {
            "task_id": task_id,
            "task_type": task_type,
            "state": "pending",
            "phase": "sending_goal",
            "source": source,
            "point_ids": point_ids,
            "index": 0,
            "progress": 0,
            "detail": "正在向 Nav2 发送目标。",
            "stop_seconds": float(route.get("stop_seconds", 0)) if command == "start_patrol" else 0.0,
        }
        self._send_current_goal(pending)

    def _send_current_goal(self, pending: CommandRequest | None) -> None:
        if not self._context:
            if pending:
                self._reply(pending, False, "unknown", "任务上下文不存在。")
            return
        waypoint_id = self._context["point_ids"][self._context["index"]]
        waypoint = self._require_waypoint(waypoint_id)
        pose = waypoint["pose"]
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = os.getenv("NAV_MISSION_FRAME_ID", "map")
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(pose["x"])
        goal.pose.pose.position.y = float(pose["y"])
        yaw = float(pose.get("yaw", 0.0))
        goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw / 2.0)
        self._context.update(
            state="pending", phase="sending_goal", current_waypoint_id=waypoint_id,
            detail=f"正在发送目标：{waypoint['name']}。",
        )
        self._initial_distance = None
        try:
            future = self._action.send_goal_async(goal, feedback_callback=self._on_feedback)
        except Exception as exc:
            self._fail(f"发送 Nav2 Goal 失败：{exc}", pending)
            return
        future.add_done_callback(self._on_goal_response)
        if pending:
            self._reply(pending, True, pending.payload["command"], "导航任务已进入 Nav2 Goal 发送队列。")

    def _on_goal_response(self, future) -> None:
        self.get_logger().info("Nav2 goal response received")
        try:
            handle = future.result()
        except Exception as exc:
            self._fail(f"发送 Nav2 Goal 失败：{exc}", None)
            return
        if not handle.accepted:
            self._fail("Nav2 拒绝了目标点。", None)
            return
        self._goal_handle = handle
        if self._cancel_mode is not None and self._cancel_request is not None:
            cancel_future = handle.cancel_goal_async()
            cancel_future.add_done_callback(
                lambda result: self._on_cancel_response(result, self._cancel_mode or "cancel", self._cancel_request)
            )
            result_future = handle.get_result_async()
            result_future.add_done_callback(self._on_result)
            return
        assert self._context is not None
        self._context.update(state="running", phase="navigating", detail="Nav2 已受理导航目标。")
        self._emit("started", "running", self._context["detail"])
        result_future = handle.get_result_async()
        result_future.add_done_callback(self._on_result)

    def _on_feedback(self, message) -> None:
        if not self._context:
            return
        now = time.monotonic()
        if now - self._last_feedback_at < 0.5:
            return
        self._last_feedback_at = now
        distance = max(0.0, float(message.feedback.distance_remaining))
        if self._initial_distance is None or distance > self._initial_distance:
            self._initial_distance = max(distance, 0.01)
        leg_progress = int(max(0, min(99, (1.0 - distance / self._initial_distance) * 100)))
        count = len(self._context["point_ids"])
        index = self._context["index"]
        progress = int(((index + leg_progress / 100.0) / count) * 100)
        self._context.update(progress=min(progress, 99), remaining_distance=distance)
        self._feedback_sequence += 1
        self._emit("progress", "running", "导航任务执行中。", event_suffix=str(self._feedback_sequence))

    def _on_result(self, future) -> None:
        self.get_logger().info("Nav2 goal result received")
        if not self._context:
            self._goal_handle = None
            return
        try:
            status = future.result().status
        except Exception as exc:
            self._goal_handle = None
            self._fail(f"读取 Nav2 结果失败：{exc}", None)
            return
        self._goal_handle = None
        if self._cancel_mode is not None:
            mode = self._cancel_mode
            pending = self._cancel_request
            self._cancel_mode = None
            self._cancel_request = None
            if pending is not None:
                self._finish_cancel(mode, pending)
            return
        if status == GoalStatus.STATUS_SUCCEEDED:
            self._arrived()
        elif status == GoalStatus.STATUS_CANCELED:
            self._fail("Nav2 Goal 被外部取消。", None)
        else:
            self._fail(f"Nav2 导航失败，状态码 {status}。", None)

    def _arrived(self) -> None:
        assert self._context is not None
        point_id = self._context["current_waypoint_id"]
        point = self._waypoints[point_id]
        self._context["remaining_distance"] = 0.0
        self._emit("arrived", "running", f"已到达{point['name']}。")
        next_index = self._context["index"] + 1
        if next_index < len(self._context["point_ids"]):
            self._context.update(index=next_index, phase="dwell", detail="巡检点停留中。")
            self._next_goal_due = time.monotonic() + max(0.0, self._context["stop_seconds"])
            return
        self._context.update(state="completed", phase="completed", progress=100, detail="导航任务已完成。")
        self._emit("completed", "completed", self._context["detail"])

    def _cancel_active(self, command: str, pending: CommandRequest) -> None:
        if not self._context or self._context.get("state") not in {"pending", "running", "paused"}:
            self._reply(pending, False, command, "当前没有可暂停或取消的活动任务。")
            return
        mode = "pause" if command == "pause_task" else "cancel"
        if self._context["state"] == "paused" and mode == "pause":
            self._reply(pending, True, command, "任务已经处于暂停状态。")
            return
        self._next_goal_due = None
        if self._goal_handle is None:
            if self._context.get("phase") == "sending_goal":
                self._cancel_mode = mode
                self._cancel_request = pending
                return
            self._finish_cancel(mode, pending)
            return
        self._cancel_mode = mode
        self._cancel_request = pending
        future = self._goal_handle.cancel_goal_async()
        future.add_done_callback(lambda result: self._on_cancel_response(result, mode, pending))

    def _on_cancel_response(self, future, mode: str, pending: CommandRequest) -> None:
        try:
            accepted = bool(future.result().goals_canceling)
        except Exception:
            accepted = False
        if not accepted:
            self._cancel_mode = None
            self._cancel_request = None
            self._reply(pending, False, pending.payload["command"], "Nav2 未确认取消当前 Goal。")
            return
        # The action result callback is the authoritative cancellation completion.

    def _finish_cancel(self, mode: str, pending: CommandRequest) -> None:
        assert self._context is not None
        if mode == "pause":
            self._context.update(state="paused", phase="paused", detail="导航任务已暂停。")
            self._emit("paused", "paused", self._context["detail"])
        else:
            self._context.update(state="cancelled", phase="cancelled", detail="导航任务已取消。")
            self._emit("cancelled", "cancelled", self._context["detail"])
        self._reply(pending, True, pending.payload["command"], self._context["detail"])

    def _resume(self, pending: CommandRequest) -> None:
        if not self._context or self._context.get("state") != "paused":
            self._reply(pending, False, "resume_task", "当前没有可恢复的暂停任务。")
            return
        if not self._action.server_is_ready():
            self._reply(pending, False, "resume_task", "Nav2 Action Server 未就绪。")
            return
        self._context.update(state="running", phase="resuming", detail="正在恢复导航任务。")
        self._emit("resumed", "running", self._context["detail"])
        self._send_current_goal(pending)

    def _fail(self, detail: str, pending: CommandRequest | None) -> None:
        if self._context:
            self._context.update(state="failed", phase="failed", detail=detail)
            self._emit("failed", "failed", detail)
        if pending:
            self._reply(pending, False, pending.payload.get("command", "unknown"), detail)

    def _reply(self, pending: CommandRequest, accepted: bool, command: str, detail: str) -> None:
        pending.response = {
            "success": True,
            "data": {
                "accepted": accepted,
                "command": command,
                "task_status": self._task_status(),
                "current_goal": self._context.get("current_waypoint_id") if self._context else None,
                "nav_state": self._nav_state(),
                "received_at": utc_now(),
                "detail": detail,
            },
        }
        pending.ready.set()

    def _task_status(self) -> dict[str, Any]:
        if not self._context:
            return {
                "task_id": "nav2-idle", "task_type": "placeholder", "state": "idle",
                "progress": 0, "source": "nav2_mission_executor", "phase": "idle",
                "current_waypoint_id": None, "waypoint_index": None, "waypoint_count": None,
                "detail": "等待任务。", "updated_at": utc_now(),
            }
        return {
            "task_id": self._context["task_id"],
            "task_type": self._context["task_type"],
            "state": self._context["state"],
            "progress": int(self._context.get("progress", 0)),
            "source": "nav2_mission_executor",
            "phase": self._context.get("phase"),
            "current_waypoint_id": self._context.get("current_waypoint_id"),
            "waypoint_index": self._context.get("index"),
            "waypoint_count": len(self._context["point_ids"]),
            "detail": self._context.get("detail"),
            "updated_at": utc_now(),
        }

    def _emit(self, event_type: str, state: str, detail: str, event_suffix: str = "") -> None:
        if not self._context:
            return
        task_id = self._context["task_id"]
        waypoint_id = self._context.get("current_waypoint_id")
        suffix = event_suffix or f"{self._context.get('index', 0)}-{waypoint_id or 'none'}"
        payload = {
            "event": {
                "event_id": f"{task_id}:{event_type}:{suffix}",
                "task_id": task_id,
                "event_type": event_type,
                "task_state": state,
                "detail": detail,
                "source": "nav2_mission_executor",
                "waypoint_id": waypoint_id,
                "remaining_distance": self._context.get("remaining_distance"),
                "progress": int(self._context.get("progress", 0)),
                "timestamp": utc_now(),
            },
            "task_status": self._task_status(),
            "current_goal": waypoint_id,
            "nav_state": self._nav_state(state),
        }
        try:
            self._updates.put_nowait(payload)
        except queue.Full:
            if event_type != "progress":
                try:
                    self._updates.get_nowait()
                    self._updates.put_nowait(payload)
                except queue.Empty:
                    pass

    def _post_updates(self) -> None:
        url = os.getenv("NAV_MISSION_BACKEND_UPDATE_URL", "http://127.0.0.1:8000/api/internal/mission/update")
        while rclpy.ok():
            try:
                payload = self._updates.get(timeout=0.5)
            except queue.Empty:
                continue
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            try:
                req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
                request.build_opener(request.ProxyHandler({})).open(req, timeout=1.0).read()
            except Exception as exc:
                self.get_logger().warning(f"Mission state update failed: {exc}")

    def _require_waypoint(self, waypoint_id: str) -> dict[str, Any]:
        waypoint = self._waypoints.get(waypoint_id)
        if waypoint is None:
            raise ValueError(f"目标点不存在：{waypoint_id}")
        if not waypoint.get("enabled", True):
            raise ValueError(f"目标点已禁用：{waypoint_id}")
        if waypoint.get("pose") is None:
            raise ValueError(f"目标点尚未配置地图坐标：{waypoint['name']} ({waypoint_id})")
        return waypoint

    def _nav_state(self, state: str | None = None) -> str:
        value = state or (self._context.get("state") if self._context else "idle")
        return {"running": "running", "paused": "paused", "completed": "completed", "failed": "failed"}.get(value, "idle")

    @staticmethod
    def _load_waypoints() -> dict[str, dict[str, Any]]:
        path = Path(os.getenv("WAYPOINTS_CONFIG_PATH", ROOT / "backend/app/config/waypoints.json"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload:
            pose = item.get("pose") if isinstance(item, dict) else None
            if isinstance(pose, (list, tuple)):
                if len(pose) < 2:
                    raise ValueError(f"目标点 pose 数组至少需要 x/y：{item.get('waypoint_id', '<unknown>')}")
                item["pose"] = {
                    "x": pose[0],
                    "y": pose[1],
                    "yaw": pose[2] if len(pose) >= 3 else 0.0,
                }
        return {str(item["waypoint_id"]): item for item in payload}

    @staticmethod
    def _load_routes() -> dict[str, dict[str, Any]]:
        path = Path(os.getenv("PATROL_ROUTES_CONFIG_PATH", ROOT / "backend/app/config/patrol_routes.json"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {str(item["route_id"]): item for item in payload}


class Handler(BaseHTTPRequestHandler):
    executor_node: MissionExecutor

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._json(404, {"error": "not_found"})
            return
        self._json(200, self.executor_node.health())

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/internal/mission":
            self._json(404, {"error": "not_found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
        except Exception:
            self._json(400, {"error": "invalid_json"})
            return
        pending = CommandRequest(payload=payload)
        if not self.executor_node.enqueue(pending):
            self._json(503, {"error": "command_queue_full"})
            return
        if not pending.ready.wait(timeout=6.0):
            self._json(504, {"error": "executor_timeout"})
            return
        self._json(200, pending.response or {"error": "empty_response"})

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def validate_config() -> int:
    waypoints = MissionExecutor._load_waypoints()
    routes = MissionExecutor._load_routes()
    configured = [key for key, value in waypoints.items() if value.get("pose") is not None]
    print(json.dumps({"waypoints": len(waypoints), "configured": configured, "routes": list(routes)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    if args.check_config:
        return validate_config()

    rclpy.init()
    node = MissionExecutor()
    Handler.executor_node = node
    server = ThreadingHTTPServer(("127.0.0.1", int(os.getenv("NAV_MISSION_EXECUTOR_PORT", "9101"))), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    ros_executor = MultiThreadedExecutor(num_threads=2)
    ros_executor.add_node(node)
    try:
        ros_executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
