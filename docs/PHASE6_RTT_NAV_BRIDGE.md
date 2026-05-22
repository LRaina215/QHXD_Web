# Phase 6 rtt_nav_bridge 使用说明

## 包位置

```text
/home/robomaster/QHXD/rtt_nav_bridge
```

节点：

```text
rtt_nav_bridge_node
```

职责：

```text
C板 USB CDC / 串口 <-> rtt_nav_bridge_node <-> /odom /imu/data /cmd_vel /tf /rtt/status
```

## 构建

```bash
cd /home/robomaster/QHXD
source /opt/ros/humble/setup.bash
colcon build --packages-select rtt_nav_bridge
source install/setup.bash
```

## 启动

使用默认 YAML：

```bash
ros2 launch rtt_nav_bridge rtt_nav_bridge.launch.py
```

直接 run：

```bash
ros2 run rtt_nav_bridge rtt_nav_bridge_node --ros-args \
  -p port:=/dev/ttyACM0 \
  -p baudrate:=115200
```

无 C 板连接时，节点会持续运行并在 `/rtt/status` 中报告 disconnected，不会崩溃。

## 当前 C 板协议兼容说明

当前真实 C 板仍按 `transmission/` 与 `timedserial/` 中的 RoboMaster 0xA5 二进制协议上发数据，不是 Phase6 文本协议。bridge 已按 `timedserial/UartIMU/packet.hpp` 和 `transmission/transmission_task.c` 兼容解析：

```text
SOF=0xA5 + data_length + seq + CRC8 + cmd_id + payload + CRC16
CMD_MCU_DATA   0x1021: curr_yaw/curr_pitch/curr_roll/shoot_speed/autoaim_mode
CMD_ROBOT_DATA 0x1022: robot HP/status payload
```

默认 YAML 使用：

```text
rx_protocol: binary_rm
binary_angle_unit: degrees
binary_yaw_clockwise_positive: true
```

`0x1021` 目前只能提供姿态角，bridge 会发布 `/imu/data` 的 orientation；该旧二进制帧没有底盘里程计 `x/y/vx/vy/wz`，所以不会凭空发布 `/odom`。`binary_rm` 模式下 bridge 只发送 `0x0500` 二进制心跳，不把 `/cmd_vel` 强行映射到旧 `0x0503` 云台自瞄控制包。`/odom` 和底盘 `/cmd_vel` 闭环需要 C 板后续实现 Phase6 `ODOM/CMD` 文本帧，或新增等价 0xA5 二进制导航里程计/底盘速度帧。

## 关键参数

```text
port: /dev/ttyACM0
baudrate: 115200
rx_protocol: binary_rm | text | auto
binary_angle_unit: degrees | radians
binary_yaw_clockwise_positive: true
base_frame_id: base_link
odom_frame_id: odom
imu_frame_id: imu_link
cmd_vel_topic: /cmd_vel
odom_topic: /odom
imu_topic: /imu/data
cmd_timeout_ms: 300
heartbeat_period_ms: 100
rx_timeout_ms: 1000
max_vx: 0.5
max_vy: 0.5
max_wz: 1.0
integrate_odom: true
publish_tf: true
```

调车初期建议把速度限幅改得更保守：

```bash
ros2 run rtt_nav_bridge rtt_nav_bridge_node --ros-args \
  -p max_vx:=0.15 \
  -p max_vy:=0.15 \
  -p max_wz:=0.3
```

## C 板上发样例

当前实物 C 板二进制上发：

```text
0x1021 CMD_MCU_DATA: <ffffB curr_yaw, curr_pitch, curr_roll, shoot_speed, autoaim_mode>
0x1022 CMD_ROBOT_DATA: <16H + B robot status>
```

Phase6 文本导航协议计划上发：

```text
ODOM,123456,1.20,0.30,0.10,0.05,0.00,0.01
IMU,123456,0.9987,0.0,0.0,0.0500,0.0,0.0,0.01,0.0,0.0,9.81
STAT,123456,auto,24000,0,0
```

速度-only odom：

```text
ODOM,123456,0.05,0.00,0.01
```

`integrate_odom=true` 时，RK3588 会临时积分出 `x/y/yaw`。

## RK3588 下发样例

```text
CMD,123500,0.100000,0.000000,0.000000
HB,123500
STOP,124000,cmd_timeout
```

## Mock C 板串口测试

无真实 C 板导航帧时，可以先开一个 mock 串口：

```bash
cd /home/robomaster/QHXD
./scripts/phase6_mock_cboard.py
```

脚本第一行会打印伪终端路径，例如 `/dev/pts/5`。另开终端启动 bridge：

```bash
source /opt/ros/humble/setup.bash
source /home/robomaster/QHXD/install/setup.bash
ros2 run rtt_nav_bridge rtt_nav_bridge_node --ros-args -p port:=/dev/pts/5
```

随后检查 `/odom`、`/imu/data`、`/rtt/status` 和 `odom -> base_link`。

## Topic 是否代表真实数据

`ros2 topic list` 只能说明系统里存在 publisher 或 subscriber，不等于 C 板已经上发了真实数据。

当前 bridge 的策略：

- `/rtt/status` 会一直存在，用于查看连接、收发计数和错误状态；
- `/cmd_vel` 会一直存在，因为 bridge 订阅它等待 Nav2 或手动速度命令；
- `/odom` 只有收到第一帧合法 `ODOM` 或后续等价导航里程计二进制帧后才创建；
- `/imu/data` 只有收到第一帧合法 `IMU`，或当前 C 板 `0x1021 CMD_MCU_DATA` 姿态帧后才创建；
- `/tf` 中的 `odom -> base_link` 只有收到合法 `ODOM` 后才广播；
- `/rtt/raw_rx` 和 `/rtt/raw_tx` 只有实际发生原始收发后才出现。

判断 C 板是否真的在上发数据，优先看：

```bash
ros2 topic echo /rtt/status --once
```

关键字段：

```text
connected=true/false
rx_count>0
rx_hz_1s>0
rx_stale=false
binary_attitude_count>0   # 当前 timedserial 二进制协议下
message=OK
```

如果 `connected=false`，说明串口设备不存在或打不开。
如果 `connected=true` 但 `rx_count=0`、`rx_stale=true`，说明串口能打开，但没有收到 C 板上发帧。

## 验收命令

```bash
ros2 topic list | grep -E 'odom|imu|rtt'
ros2 topic echo /imu/data --once
ros2 topic echo /odom --once
ros2 run tf2_ros tf2_echo odom base_link
ros2 topic echo /rtt/status --once
```

手动下发低速速度：

```bash
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
```

停止发布后，bridge 会在 `cmd_timeout_ms` 后发送 0 速度和 `STOP,...,cmd_timeout`。

## slam_toolbox 联调顺序

1. 启动 MID-360；
2. 启动 pointcloud_to_laserscan，确认 `/scan` 稳定；
3. 启动 `rtt_nav_bridge`，确认 `/odom` 和 `odom -> base_link`；
4. 启动 `slam_toolbox`；
5. 检查 TF 树：`map -> odom -> base_link -> livox_frame`；
6. 低速移动机器人，观察 `/map` 是否持续更新。

## Nav2 基础联调顺序

1. 启动 map_server；
2. 启动 AMCL；
3. 启动 Nav2；
4. 确认 lifecycle nodes active；
5. 在 RViz2 下发短距离目标；
6. 确认 Nav2 输出 `/cmd_vel`；
7. 确认 C 板收到 `CMD` 且底盘低速向目标方向运动。

## 安全边界

- YOLO、语音、Dashboard 不参与本阶段底盘控制。
- bridge 不绕过 C 板急停逻辑。
- `STAT.estop=1` 时 bridge 拒绝转发非零速度。
- bridge 退出时尽量发送 `STOP,...,bridge_shutdown`。
- C 板仍必须实现本地 CMD/HB 超时停车。
