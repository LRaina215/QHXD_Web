#!/usr/bin/env python3
import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from urllib import error, request

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp_to_iso(msg: Imu) -> str:
    sec = int(msg.header.stamp.sec)
    nanosec = int(msg.header.stamp.nanosec)
    if sec <= 0:
        return utc_now_iso()
    return datetime.fromtimestamp(sec + nanosec / 1_000_000_000.0, timezone.utc).isoformat()


def quaternion_to_euler_deg(x: float, y: float, z: float, w: float) -> dict[str, float]:
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1.0:
        pitch = math.copysign(math.pi / 2.0, sinp)
    else:
        pitch = math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return {
        "yaw": math.degrees(yaw),
        "pitch": math.degrees(pitch),
        "roll": math.degrees(roll),
    }


def imu_payload(msg: Imu, source: str) -> dict:
    orientation = msg.orientation
    timestamp = stamp_to_iso(msg)
    frame_id = msg.header.frame_id or "imu_link"
    return {
        "source": source,
        "updated_at": utc_now_iso(),
        "imu": {
            "frame_id": frame_id,
            "timestamp": timestamp,
            "orientation": {
                "x": orientation.x,
                "y": orientation.y,
                "z": orientation.z,
                "w": orientation.w,
            },
            "euler_deg": quaternion_to_euler_deg(
                orientation.x,
                orientation.y,
                orientation.z,
                orientation.w,
            ),
            "angular_velocity": {
                "x": msg.angular_velocity.x,
                "y": msg.angular_velocity.y,
                "z": msg.angular_velocity.z,
            },
            "linear_acceleration": {
                "x": msg.linear_acceleration.x,
                "y": msg.linear_acceleration.y,
                "z": msg.linear_acceleration.z,
            },
        },
    }


class Ros2ImuBridge(Node):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__("qhxd_ros2_imu_bridge")
        self.backend_url = args.backend_url.rstrip("/")
        self.endpoint = f"{self.backend_url}/api/internal/nuc/imu"
        self.source = args.source
        self.min_interval = 1.0 / args.rate_hz
        self.timeout_s = args.timeout_s
        self._last_post_at = 0.0
        self._last_message_at = 0.0
        self._accepted_count = 0
        self._error_count = 0
        self._last_log_at = 0.0
        self.create_subscription(Imu, args.topic, self._on_imu, 10)
        self.create_timer(5.0, self._check_stale)
        self.get_logger().info(
            f"Bridge {args.topic} -> {self.endpoint}, source={self.source}, rate={args.rate_hz:.1f} Hz"
        )

    def _on_imu(self, msg: Imu) -> None:
        now = time.monotonic()
        self._last_message_at = now
        if now - self._last_post_at < self.min_interval:
            return
        self._last_post_at = now

        body = json.dumps(imu_payload(msg, self.source)).encode("utf-8")
        http_request = request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
            data = json.loads(raw)
            result = data.get("data", {})
            if result.get("accepted") is True and result.get("imu_updated") is True:
                self._accepted_count += 1
                if now - self._last_log_at >= 5.0:
                    self.get_logger().info(f"accepted IMU samples: {self._accepted_count}")
                    self._last_log_at = now
            else:
                detail = result.get("detail", "backend did not accept IMU sample")
                self.get_logger().warning(detail)
        except (error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            self._error_count += 1
            if now - self._last_log_at >= 5.0:
                self.get_logger().warning(
                    f"failed to post IMU sample: {type(exc).__name__}: {exc}; errors={self._error_count}"
                )
                self._last_log_at = now

    def _check_stale(self) -> None:
        now = time.monotonic()
        if self._last_message_at <= 0.0:
            self.get_logger().warning("waiting for IMU messages on subscribed ROS 2 topic")
        elif now - self._last_message_at > 5.0:
            self.get_logger().warning(
                f"no IMU message received for {now - self._last_message_at:.1f} s"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bridge ROS2 /serial/imu to QHXD backend IMU API.")
    parser.add_argument("--topic", default="/serial/imu")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--source", default="rk3588_cboard_ros2")
    parser.add_argument("--rate-hz", type=float, default=20.0)
    parser.add_argument("--timeout-s", type=float, default=1.0)
    args = parser.parse_args()
    if args.rate_hz <= 0:
        parser.error("--rate-hz must be positive")
    return args


def main() -> int:
    args = parse_args()
    rclpy.init()
    node = Ros2ImuBridge(args)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
