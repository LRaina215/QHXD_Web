from __future__ import annotations

import math
import time
from typing import Any

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster

from .protocol import (
    ImuFrame,
    OdomFrame,
    ProtocolError,
    StatFrame,
    format_cmd,
    format_heartbeat,
    format_stop,
    euler_to_quaternion,
    parse_nav_line,
    yaw_to_quaternion,
)
from .rm_binary_protocol import (
    CMD_HEARTBEAT,
    BinaryAttitudeFrame,
    BinaryRobotStatusFrame,
    RmBinaryFrameParser,
    UnknownBinaryFrame,
    build_binary_frame,
)
from .serial_transport import SerialTransport


class RttNavBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__('rtt_nav_bridge_node')
        self._declare_parameters()
        self._load_parameters()

        self.odom_pub = None
        self.imu_pub = None
        self.raw_rx_pub = None
        self.raw_tx_pub = None
        self.tf_broadcaster = None
        self.diag_pub = self.create_publisher(DiagnosticArray, self.status_topic, 10)
        self.cmd_sub = self.create_subscription(Twist, self.cmd_vel_topic, self._on_cmd_vel, 10)

        self.transport = SerialTransport(self.port, self.baudrate)
        self.connected = False
        self.estop = False
        self.mode = 'unknown'
        self.battery_mv = 0
        self.fault_code = 0

        self.rx_count = 0
        self.tx_count = 0
        self.parse_error_count = 0
        self.serial_error_count = 0
        self.last_rx_count = 0
        self.last_tx_count = 0
        self.rx_hz = 0.0
        self.tx_hz = 0.0
        self.last_rate_time = self.get_clock().now()
        self.last_rx_time = None
        self.last_cmd_time = None
        self.cmd_timeout_active = False
        self.last_odom_board_ms = None
        self.binary_parser = RmBinaryFrameParser()
        self.text_rx_buffer = bytearray()
        self.binary_attitude_count = 0
        self.binary_robot_status_count = 0
        self.unknown_binary_count = 0
        self.binary_cmd_vel_warned = False
        self.odom_x = 0.0
        self.odom_y = 0.0
        self.odom_yaw = 0.0

        self.reconnect_timer = self.create_timer(self.reconnect_period_ms / 1000.0, self._ensure_connection)
        self.read_timer = self.create_timer(0.01, self._read_serial)
        self.heartbeat_timer = self.create_timer(self.heartbeat_period_ms / 1000.0, self._send_heartbeat)
        self.safety_timer = self.create_timer(0.05, self._check_safety)
        self.diagnostic_timer = self.create_timer(1.0, self._publish_diagnostics)

        self._ensure_connection()
        self.get_logger().info(
            f'rtt_nav_bridge started: port={self.port}, baudrate={self.baudrate}, '
            f'cmd_vel={self.cmd_vel_topic}, odom={self.odom_topic}, imu={self.imu_topic}'
        )

    def _declare_parameters(self) -> None:
        defaults: dict[str, Any] = {
            'port': '/dev/ttyACM0',
            'baudrate': 115200,
            'base_frame_id': 'base_link',
            'odom_frame_id': 'odom',
            'imu_frame_id': 'imu_link',
            'cmd_vel_topic': '/cmd_vel',
            'odom_topic': '/odom',
            'imu_topic': '/imu/data',
            'status_topic': '/rtt/status',
            'raw_rx_topic': '/rtt/raw_rx',
            'raw_tx_topic': '/rtt/raw_tx',
            'publish_raw': True,
            'rx_protocol': 'auto',
            'binary_angle_unit': 'degrees',
            'binary_yaw_clockwise_positive': True,
            'cmd_timeout_ms': 300,
            'heartbeat_period_ms': 100,
            'reconnect_period_ms': 1000,
            'rx_timeout_ms': 1000,
            'max_vx': 0.5,
            'max_vy': 0.5,
            'max_wz': 1.0,
            'integrate_odom': True,
            'publish_tf': True,
            'pose_covariance_diagonal': [0.02, 0.02, 0.0, 0.0, 0.0, 0.05],
            'twist_covariance_diagonal': [0.05, 0.05, 0.0, 0.0, 0.0, 0.1],
            'imu_orientation_covariance_diagonal': [0.05, 0.05, 0.1],
            'imu_angular_velocity_covariance_diagonal': [0.02, 0.02, 0.02],
            'imu_linear_acceleration_covariance_diagonal': [0.2, 0.2, 0.2],
        }
        for name, default in defaults.items():
            self.declare_parameter(name, default)

    def _load_parameters(self) -> None:
        self.port = self.get_parameter('port').value
        self.baudrate = int(self.get_parameter('baudrate').value)
        self.base_frame_id = self.get_parameter('base_frame_id').value
        self.odom_frame_id = self.get_parameter('odom_frame_id').value
        self.imu_frame_id = self.get_parameter('imu_frame_id').value
        self.cmd_vel_topic = self.get_parameter('cmd_vel_topic').value
        self.odom_topic = self.get_parameter('odom_topic').value
        self.imu_topic = self.get_parameter('imu_topic').value
        self.status_topic = self.get_parameter('status_topic').value
        self.raw_rx_topic = self.get_parameter('raw_rx_topic').value
        self.raw_tx_topic = self.get_parameter('raw_tx_topic').value
        self.publish_raw = bool(self.get_parameter('publish_raw').value)
        self.rx_protocol = str(self.get_parameter('rx_protocol').value).lower()
        self.binary_angle_unit = str(self.get_parameter('binary_angle_unit').value).lower()
        self.binary_yaw_clockwise_positive = bool(self.get_parameter('binary_yaw_clockwise_positive').value)
        self.cmd_timeout_ms = int(self.get_parameter('cmd_timeout_ms').value)
        self.heartbeat_period_ms = int(self.get_parameter('heartbeat_period_ms').value)
        self.reconnect_period_ms = int(self.get_parameter('reconnect_period_ms').value)
        self.rx_timeout_ms = int(self.get_parameter('rx_timeout_ms').value)
        self.max_vx = float(self.get_parameter('max_vx').value)
        self.max_vy = float(self.get_parameter('max_vy').value)
        self.max_wz = float(self.get_parameter('max_wz').value)
        self.integrate_odom = bool(self.get_parameter('integrate_odom').value)
        self.publish_tf = bool(self.get_parameter('publish_tf').value)
        self.pose_cov_diag = _as_float_list(self.get_parameter('pose_covariance_diagonal').value, 6)
        self.twist_cov_diag = _as_float_list(self.get_parameter('twist_covariance_diagonal').value, 6)
        self.imu_orientation_cov_diag = _as_float_list(self.get_parameter('imu_orientation_covariance_diagonal').value, 3)
        self.imu_angular_velocity_cov_diag = _as_float_list(self.get_parameter('imu_angular_velocity_covariance_diagonal').value, 3)
        self.imu_linear_acceleration_cov_diag = _as_float_list(self.get_parameter('imu_linear_acceleration_covariance_diagonal').value, 3)

    def _ensure_connection(self) -> None:
        if self.transport.is_open:
            self.connected = True
            return
        try:
            self.transport.open()
        except Exception as exc:
            if self.connected:
                self.get_logger().error(f'C-board serial disconnected: {exc}')
            else:
                self.get_logger().warn(f'C-board serial unavailable on {self.port}: {exc}', throttle_duration_sec=5.0)
            self.connected = False
            return
        self.connected = True
        self.get_logger().info(f'C-board serial connected: {self.port} @ {self.baudrate}')

    def _read_serial(self) -> None:
        if not self.transport.is_open:
            return
        try:
            data = self.transport.read_bytes()
        except Exception as exc:
            self.serial_error_count += 1
            self.connected = False
            self.transport.close()
            self.get_logger().error(f'serial read failed: {exc}')
            return
        if not data:
            return
        for frame in self._parse_rx_bytes(data):
            self._handle_rx_frame(frame)

    def _parse_rx_bytes(self, data: bytes) -> list[Any]:
        if self.rx_protocol == 'binary_rm':
            return self.binary_parser.feed(data)
        if self.rx_protocol == 'text':
            return self._parse_text_bytes(data)
        if b'\xa5' in data or self.binary_parser.buffer:
            frames = self.binary_parser.feed(data)
            if frames:
                return frames
            return []
        return self._parse_text_bytes(data)

    def _parse_text_bytes(self, data: bytes) -> list[Any]:
        self.text_rx_buffer.extend(data)
        frames: list[Any] = []
        while b'\n' in self.text_rx_buffer:
            raw, _, rest = self.text_rx_buffer.partition(b'\n')
            self.text_rx_buffer = bytearray(rest)
            line = raw.decode('utf-8', errors='replace').strip()
            if not line:
                continue
            if self.publish_raw:
                self._publish_raw_rx(line)
            try:
                frames.append(parse_nav_line(line))
            except ProtocolError as exc:
                self.parse_error_count += 1
                self.get_logger().warn(f'bad C-board text frame: {exc}; raw={line}', throttle_duration_sec=2.0)
        if len(self.text_rx_buffer) > 8192:
            self.parse_error_count += 1
            del self.text_rx_buffer[:-4096]
        return frames

    def _handle_rx_frame(self, frame: Any) -> None:
        self.rx_count += 1
        self.last_rx_time = self.get_clock().now()
        if isinstance(frame, OdomFrame):
            self._publish_odom(frame)
        elif isinstance(frame, ImuFrame):
            self._publish_imu(frame)
        elif isinstance(frame, StatFrame):
            self._update_status(frame)
        elif isinstance(frame, BinaryAttitudeFrame):
            self._publish_binary_attitude(frame)
        elif isinstance(frame, BinaryRobotStatusFrame):
            self._update_binary_robot_status(frame)
        elif isinstance(frame, UnknownBinaryFrame):
            self.unknown_binary_count += 1
            self.get_logger().warn(
                f'unknown C-board binary frame: cmd_id=0x{frame.cmd_id:04x}, payload_len={frame.payload_len}',
                throttle_duration_sec=2.0,
            )

    def _publish_imu(self, frame: ImuFrame) -> None:
        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.imu_frame_id
        msg.orientation.w = frame.qw
        msg.orientation.x = frame.qx
        msg.orientation.y = frame.qy
        msg.orientation.z = frame.qz
        msg.angular_velocity.x = frame.gx
        msg.angular_velocity.y = frame.gy
        msg.angular_velocity.z = frame.gz
        msg.linear_acceleration.x = frame.ax
        msg.linear_acceleration.y = frame.ay
        msg.linear_acceleration.z = frame.az
        _fill_diagonal(msg.orientation_covariance, self.imu_orientation_cov_diag)
        _fill_diagonal(msg.angular_velocity_covariance, self.imu_angular_velocity_cov_diag)
        _fill_diagonal(msg.linear_acceleration_covariance, self.imu_linear_acceleration_cov_diag)
        self._publish_imu_msg(msg)

    def _publish_odom(self, frame: OdomFrame) -> None:
        if frame.pose_valid:
            self.odom_x = float(frame.x)
            self.odom_y = float(frame.y)
            self.odom_yaw = float(frame.yaw)
        elif self.integrate_odom:
            self._integrate_odom(frame)
        qw, qx, qy, qz = yaw_to_quaternion(self.odom_yaw)

        msg = Odometry()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.odom_frame_id
        msg.child_frame_id = self.base_frame_id
        msg.pose.pose.position.x = self.odom_x
        msg.pose.pose.position.y = self.odom_y
        msg.pose.pose.position.z = 0.0
        msg.pose.pose.orientation.w = qw
        msg.pose.pose.orientation.x = qx
        msg.pose.pose.orientation.y = qy
        msg.pose.pose.orientation.z = qz
        msg.twist.twist.linear.x = frame.vx
        msg.twist.twist.linear.y = frame.vy
        msg.twist.twist.angular.z = frame.wz
        _fill_diagonal(msg.pose.covariance, self.pose_cov_diag)
        _fill_diagonal(msg.twist.covariance, self.twist_cov_diag)
        self._publish_odom_msg(msg)
        if self.publish_tf:
            self._publish_odom_tf(msg)

    def _integrate_odom(self, frame: OdomFrame) -> None:
        if self.last_odom_board_ms is None:
            self.last_odom_board_ms = frame.timestamp_ms
            return
        dt = max(0.0, min(0.2, (frame.timestamp_ms - self.last_odom_board_ms) / 1000.0))
        self.last_odom_board_ms = frame.timestamp_ms
        dx = (frame.vx * math.cos(self.odom_yaw) - frame.vy * math.sin(self.odom_yaw)) * dt
        dy = (frame.vx * math.sin(self.odom_yaw) + frame.vy * math.cos(self.odom_yaw)) * dt
        self.odom_x += dx
        self.odom_y += dy
        self.odom_yaw = _normalize_angle(self.odom_yaw + frame.wz * dt)

    def _publish_odom_tf(self, odom: Odometry) -> None:
        tf = TransformStamped()
        tf.header = odom.header
        tf.child_frame_id = odom.child_frame_id
        tf.transform.translation.x = odom.pose.pose.position.x
        tf.transform.translation.y = odom.pose.pose.position.y
        tf.transform.translation.z = 0.0
        tf.transform.rotation = odom.pose.pose.orientation
        if self.tf_broadcaster is None:
            self.tf_broadcaster = TransformBroadcaster(self)
        self.tf_broadcaster.sendTransform(tf)

    def _publish_binary_attitude(self, frame: BinaryAttitudeFrame) -> None:
        self.binary_attitude_count += 1
        roll = self._binary_angle_to_rad(frame.curr_roll)
        pitch = self._binary_angle_to_rad(frame.curr_pitch)
        yaw = self._binary_angle_to_rad(frame.curr_yaw)
        if self.binary_yaw_clockwise_positive:
            yaw = -yaw
        qw, qx, qy, qz = euler_to_quaternion(roll, pitch, yaw)

        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.imu_frame_id
        msg.orientation.w = qw
        msg.orientation.x = qx
        msg.orientation.y = qy
        msg.orientation.z = qz
        _fill_diagonal(msg.orientation_covariance, self.imu_orientation_cov_diag)
        msg.angular_velocity_covariance[0] = -1.0
        msg.linear_acceleration_covariance[0] = -1.0
        self.mode = f'autoaim:{frame.autoaim_mode}'
        self._publish_imu_msg(msg)
        if self.publish_raw:
            self._publish_raw_rx(
                f'BINARY,0x1021,yaw={frame.curr_yaw:.3f},pitch={frame.curr_pitch:.3f},'
                f'roll={frame.curr_roll:.3f},shoot_speed={frame.shoot_speed:.3f},mode={frame.autoaim_mode}'
            )

    def _update_binary_robot_status(self, frame: BinaryRobotStatusFrame) -> None:
        self.binary_robot_status_count += 1
        if self.publish_raw:
            self._publish_raw_rx(f'BINARY,0x1022,robot_id={frame.robot_id},hp0={frame.hp_values[0] if frame.hp_values else 0}')

    def _binary_angle_to_rad(self, value: float) -> float:
        if self.binary_angle_unit in ('degree', 'degrees', 'deg'):
            return math.radians(value)
        return value

    def _publish_odom_msg(self, msg: Odometry) -> None:
        if self.odom_pub is None:
            self.odom_pub = self.create_publisher(Odometry, self.odom_topic, 10)
            self.get_logger().info(f'created odom publisher after first valid ODOM frame: {self.odom_topic}')
        self.odom_pub.publish(msg)

    def _publish_imu_msg(self, msg: Imu) -> None:
        if self.imu_pub is None:
            self.imu_pub = self.create_publisher(Imu, self.imu_topic, 10)
            self.get_logger().info(f'created imu publisher after first valid IMU frame: {self.imu_topic}')
        self.imu_pub.publish(msg)

    def _publish_raw_rx(self, line: str) -> None:
        if self.raw_rx_pub is None:
            self.raw_rx_pub = self.create_publisher(String, self.raw_rx_topic, 10)
        self.raw_rx_pub.publish(String(data=line))

    def _publish_raw_tx(self, line: str) -> None:
        if self.raw_tx_pub is None:
            self.raw_tx_pub = self.create_publisher(String, self.raw_tx_topic, 10)
        try:
            self.raw_tx_pub.publish(String(data=line))
        except Exception:
            pass

    def _update_status(self, frame: StatFrame) -> None:
        self.mode = frame.mode
        self.battery_mv = frame.battery_mv
        self.estop = frame.estop
        self.fault_code = frame.fault_code
        if self.estop:
            self._send_stop('estop')

    def _on_cmd_vel(self, msg: Twist) -> None:
        vx = _clip(msg.linear.x, -self.max_vx, self.max_vx)
        vy = _clip(msg.linear.y, -self.max_vy, self.max_vy)
        wz = _clip(msg.angular.z, -self.max_wz, self.max_wz)
        if self.estop:
            vx, vy, wz = 0.0, 0.0, 0.0
        self.last_cmd_time = self.get_clock().now()
        self.cmd_timeout_active = False
        if not self.connected:
            self.get_logger().warn('drop cmd_vel because C-board serial is not connected', throttle_duration_sec=2.0)
            return
        self._send_cmd(vx, vy, wz)

    def _send_cmd(self, vx: float, vy: float, wz: float) -> None:
        if self.rx_protocol == 'binary_rm':
            if not self.binary_cmd_vel_warned:
                self.get_logger().warn(
                    'binary_rm mode matches current timedserial C-board protocol; /cmd_vel chassis command is not mapped to 0x0503 gimbal control'
                )
                self.binary_cmd_vel_warned = True
            return
        self._write_nav_line(format_cmd(_ms_now(), vx, vy, wz))

    def _send_heartbeat(self) -> None:
        if not self.connected:
            return
        if self.rx_protocol == 'binary_rm':
            self._write_binary_frame(CMD_HEARTBEAT, bytes([0]), 'BINARY,0x0500,mode=0')
        else:
            self._write_nav_line(format_heartbeat(_ms_now()))

    def _send_stop(self, reason: str) -> None:
        if self.connected:
            self._send_cmd(0.0, 0.0, 0.0)
            if self.rx_protocol == 'binary_rm':
                self._write_binary_frame(CMD_HEARTBEAT, bytes([0]), f'BINARY,0x0500,mode=0,reason={reason}')
            else:
                self._write_nav_line(format_stop(_ms_now(), reason))

    def _write_binary_frame(self, cmd_id: int, payload: bytes, raw_line: str) -> None:
        try:
            self.transport.write_bytes(build_binary_frame(cmd_id, payload))
        except Exception as exc:
            self.serial_error_count += 1
            self.connected = False
            self.transport.close()
            self.get_logger().error(f'serial write failed: {exc}')
            return
        self.tx_count += 1
        if self.publish_raw and rclpy.ok():
            self._publish_raw_tx(raw_line)

    def _write_nav_line(self, line: str) -> None:
        try:
            self.transport.write_line(line)
        except Exception as exc:
            self.serial_error_count += 1
            self.connected = False
            self.transport.close()
            self.get_logger().error(f'serial write failed: {exc}')
            return
        self.tx_count += 1
        if self.publish_raw and rclpy.ok():
            self._publish_raw_tx(line.strip())

    def _check_safety(self) -> None:
        if self.last_cmd_time is None or self.cmd_timeout_active:
            return
        elapsed_ms = (self.get_clock().now() - self.last_cmd_time).nanoseconds / 1_000_000.0
        if elapsed_ms > self.cmd_timeout_ms:
            self.cmd_timeout_active = True
            self._send_stop('cmd_timeout')

    def _publish_diagnostics(self) -> None:
        now = self.get_clock().now()
        elapsed = max(1e-6, (now - self.last_rate_time).nanoseconds / 1_000_000_000.0)
        self.rx_hz = (self.rx_count - self.last_rx_count) / elapsed
        self.tx_hz = (self.tx_count - self.last_tx_count) / elapsed
        self.last_rx_count = self.rx_count
        self.last_tx_count = self.tx_count
        self.last_rate_time = now

        status = DiagnosticStatus()
        status.name = 'rtt_nav_bridge'
        status.hardware_id = self.port
        rx_stale = self._rx_is_stale(now)
        if self.estop or self.fault_code != 0:
            status.level = DiagnosticStatus.ERROR
            status.message = 'C-board reports estop or fault'
        elif not self.connected:
            status.level = DiagnosticStatus.WARN
            status.message = 'C-board serial disconnected'
        elif rx_stale:
            status.level = DiagnosticStatus.WARN
            status.message = 'C-board serial open but no recent RX frame'
        elif self.cmd_timeout_active:
            status.level = DiagnosticStatus.WARN
            status.message = 'cmd_vel timeout; zero command sent'
        else:
            status.level = DiagnosticStatus.OK
            status.message = 'OK'
        status.values = [
            KeyValue(key='connected', value=str(self.connected)),
            KeyValue(key='port', value=self.port),
            KeyValue(key='baudrate', value=str(self.baudrate)),
            KeyValue(key='mode', value=str(self.mode)),
            KeyValue(key='battery_mv', value=str(self.battery_mv)),
            KeyValue(key='estop', value=str(int(self.estop))),
            KeyValue(key='fault_code', value=str(self.fault_code)),
            KeyValue(key='rx_hz_1s', value=f'{self.rx_hz:.2f}'),
            KeyValue(key='tx_hz_1s', value=f'{self.tx_hz:.2f}'),
            KeyValue(key='rx_count', value=str(self.rx_count)),
            KeyValue(key='tx_count', value=str(self.tx_count)),
            KeyValue(key='parse_error_count', value=str(self.parse_error_count)),
            KeyValue(key='rx_protocol', value=self.rx_protocol),
            KeyValue(key='binary_attitude_count', value=str(self.binary_attitude_count)),
            KeyValue(key='binary_robot_status_count', value=str(self.binary_robot_status_count)),
            KeyValue(key='unknown_binary_count', value=str(self.unknown_binary_count)),
            KeyValue(key='binary_crc8_errors', value=str(self.binary_parser.crc8_errors)),
            KeyValue(key='binary_crc16_errors', value=str(self.binary_parser.crc16_errors)),
            KeyValue(key='serial_error_count', value=str(self.serial_error_count)),
            KeyValue(key='rx_timeout_ms', value=str(self.rx_timeout_ms)),
            KeyValue(key='rx_stale', value=str(rx_stale)),
            KeyValue(key='cmd_timeout_active', value=str(self.cmd_timeout_active)),
        ]
        array = DiagnosticArray()
        array.header.stamp = now.to_msg()
        array.status.append(status)
        self.diag_pub.publish(array)

    def _rx_is_stale(self, now: Any) -> bool:
        if self.rx_timeout_ms <= 0:
            return False
        if self.last_rx_time is None:
            return True
        elapsed_ms = (now - self.last_rx_time).nanoseconds / 1_000_000.0
        return elapsed_ms > self.rx_timeout_ms

    def destroy_node(self) -> bool:
        try:
            self._send_stop('bridge_shutdown')
        except Exception:
            pass
        finally:
            self.transport.close()
        return super().destroy_node()


def _fill_diagonal(covariance: Any, diagonal: list[float]) -> None:
    for index, value in enumerate(diagonal):
        covariance[index * 6 + index if len(covariance) == 36 else index * 3 + index] = float(value)


def _as_float_list(value: Any, expected_len: int) -> list[float]:
    data = [float(item) for item in value]
    if len(data) != expected_len:
        raise ValueError(f'expected {expected_len} covariance diagonal values, got {len(data)}')
    return data


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _ms_now() -> int:
    return int(time.time() * 1000)


def _normalize_angle(value: float) -> float:
    while value > math.pi:
        value -= 2.0 * math.pi
    while value < -math.pi:
        value += 2.0 * math.pi
    return value


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = RttNavBridgeNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
