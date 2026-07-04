# 2026-07-04: PolarBear Point-LIO front-end deployment

- Added `SMBU-PolarBear-Robotics-Team/point_lio` at pinned commit
  `e85e79558cf746f6699888a54285fe48b3b0ac71` to `~/livox_ws/src/point_lio`.
- Built `point_lio` successfully on RK3588 / Ubuntu 22.04 / ROS 2 Humble / ARM64.
- Added `~/livox_ws/launch/msg_MID360_pointlio_launch.py`; it publishes
  `/livox/lidar` as `livox_ros_driver2/msg/CustomMsg` without changing the
  existing PointCloud2 launch file.
- Added `~/livox_ws/config/point_lio_mid360_rk3588.yaml`; prior PCD, PCD saving,
  path output, and registered cloud output are disabled for the first low-load
  odometry validation.
- Verified `/aft_mapped_to_init` at approximately 10 Hz and verified
  `camera_init -> aft_mapped` TF.
- A 30 second stationary sample contained 287 messages. Horizontal
  end-to-start displacement was approximately 9 mm; observed x/y ranges were
  approximately 2.2 cm.
- Observed runtime footprint: Point-LIO about 26% of one CPU core / 85 MB RSS;
  Livox driver about 53% of one core / 43 MB RSS.
- Identified an RK image runtime conflict: `/opt/MVS/lib/aarch64` contains an
  old `libusb`. Point-LIO must run after `unset LD_LIBRARY_PATH` and sourcing
  ROS again, otherwise PCL reports `undefined symbol: libusb_set_option`.
- Point-LIO is deployed as the future local odometry source only. The existing
  2D slam_toolbox/Nav2/serial-control stack remains unchanged.
- Remaining integration work: project Point-LIO 6DoF pose to planar
  `odom -> base_link`, switch the 2D scan converter to a deskewed body-frame
  PointCloud2 output, and disable C-board `publish_odom/publish_odom_tf` in LIO
  navigation mode.

# PHASE6_DONE.md

## 完成内容

Phase 6 已完成第一版 RT-Thread / C 板导航通信桥接基础：

- 审阅 `transmission/` 下位机 USB CDC 通信代码和 `timedserial/` 上位机通信代码；
- 输出现有协议审阅文档：`docs/PHASE6_PROTOCOL_REVIEW.md`；
- 输出导航文本协议 v1：`docs/PHASE6_NAV_PROTOCOL_V1.md`；
- 新增 ROS2 ament_python 包：`rtt_nav_bridge`；
- 新增节点：`rtt_nav_bridge_node`；
- 新增 launch：`rtt_nav_bridge/launch/rtt_nav_bridge.launch.py`；
- 新增 YAML 配置：`rtt_nav_bridge/config/rtt_nav_bridge.yaml`；
- 新增使用说明：`docs/PHASE6_RTT_NAV_BRIDGE.md`；
- 新增 mock C 板串口脚本：`scripts/phase6_mock_cboard.py`。

## 关键实现

### 协议解析

- `rtt_nav_bridge/rtt_nav_bridge/protocol.py`
  - `parse_nav_line()` 解析 `ODOM / IMU / STAT`；
  - `format_cmd()` 生成 `CMD,timestamp_ms,vx,vy,wz`；
  - `format_heartbeat()` 生成 `HB,timestamp_ms`；
  - `format_stop()` 生成 `STOP,timestamp_ms,reason`；
  - 支持完整 ODOM 与速度-only ODOM；
  - 支持四元数 IMU 与欧拉角 IMU。

### 串口传输

- `rtt_nav_bridge/rtt_nav_bridge/serial_transport.py`
  - 使用 Python 标准库 `os/termios/select`，不依赖 pyserial；
  - 支持非阻塞读取；
  - 按 `\n` 分行；
  - 串口缺失或断开时抛出明确错误，节点不崩溃。

### ROS2 bridge 节点

- `rtt_nav_bridge/rtt_nav_bridge/rtt_nav_bridge_node.py`
  - 参数：`port/baudrate/base_frame_id/odom_frame_id/imu_frame_id/cmd_timeout_ms/heartbeat_period_ms/max_vx/max_vy/max_wz` 等；
  - 发布 `/odom`；收到第一帧合法 `ODOM` 后才懒创建 `/odom` publisher，避免未接 C 板时 `topic list` 误导；
  - 发布 `/imu/data`；收到第一帧合法 `IMU` 后才懒创建 `/imu/data` publisher；
  - 广播 `odom -> base_link`；收到合法 `ODOM` 后才创建 TF broadcaster；
  - 订阅 `/cmd_vel` 并下发 `CMD`；
  - 周期下发 `HB`；
  - `/cmd_vel` 超时下发 0 速度和 `STOP`；
  - `STAT.estop=1` 时拒绝非零速度；
  - 发布 `/rtt/status` 诊断；
  - 可选发布 `/rtt/raw_rx` 和 `/rtt/raw_tx`。

## 验证结果

已执行：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select rtt_nav_bridge
```

结果：

```text
Summary: 1 package finished
```

协议解析自检已通过：

```text
protocol_self_check=OK
```

无串口启动验证：

```bash
ros2 run rtt_nav_bridge rtt_nav_bridge_node --ros-args -p port:=/dev/phase6_missing_serial
```

结果：节点输出明确 warning 并保持运行，不崩溃。

launch 验证：

```bash
ros2 launch rtt_nav_bridge rtt_nav_bridge.launch.py config:=/home/robomaster/QHXD/rtt_nav_bridge/config/rtt_nav_bridge.yaml
```

结果：节点可启动。当前 `/dev/ttyACM0` 上是旧 0xA5 二进制通信帧，bridge 已兼容解析 `0x1021/0x1022`；可从 `0x1021` 发布 `/imu/data`，但不会伪造 `/odom`。

Mock C 板端到端验证：

```bash
./scripts/phase6_mock_cboard.py
ros2 run rtt_nav_bridge rtt_nav_bridge_node --ros-args -p port:=/dev/pts/X
ros2 topic echo /odom --once
ros2 topic echo /imu/data --once
```

结果：`/odom` 能输出 `frame_id=odom`、`child_frame_id=base_link`、`twist.linear.x=0.02`；`/imu/data` 能输出 `frame_id=imu_link`、`angular_velocity.z=0.01`、`linear_acceleration.z=9.81`。


## 真实 C 板二进制协议兼容修正

用户实机启动时出现 `bad C-board frame: unknown frame type: �`，原因是当前 C 板仍在发送 `timedserial/transmission` 的 0xA5 二进制帧，而第一版 bridge 按 Phase6 文本文本行解析串口，导致二进制字节被 UTF-8 文本解码成乱码。

已按参考代码修正：

- `rtt_nav_bridge/rtt_nav_bridge/rm_binary_protocol.py`
  - 新增 RoboMaster 0xA5 帧解析器；
  - 使用 `transmission/transmission_task.h` 同款 CRC8/CRC16 查表算法；
  - 支持 `CMD_MCU_DATA = 0x1021`，payload 为 `<ffffB>`：`curr_yaw/curr_pitch/curr_roll/shoot_speed/autoaim_mode`；
  - 支持 `CMD_ROBOT_DATA = 0x1022`，payload 为 `<16H+B>` 机器人状态；
  - 错误帧按 CRC 计数，不再作为文本乱码报警。
- `rtt_nav_bridge/rtt_nav_bridge/serial_transport.py`
  - 新增 `read_bytes()`，按原始 bytes 非阻塞读取串口，避免二进制协议被行文本读取破坏。
- `rtt_nav_bridge/rtt_nav_bridge/rtt_nav_bridge_node.py`
  - 新增 `rx_protocol` 参数：`binary_rm/text/auto`；
  - 当前默认配置使用 `binary_rm`；
  - 从 `0x1021` 姿态帧发布 `/imu/data` orientation；
  - yaw 按 `timedserial` 注释的“顺时针为正”转换为 ROS 常用逆时针为正；
  - `/rtt/status` 增加 `binary_attitude_count/binary_robot_status_count/binary_crc8_errors/binary_crc16_errors` 等诊断字段；
  - `binary_rm` 模式下发送 `0x0500` 二进制心跳，不再向旧 C 板发送文本 `HB/CMD/STOP`；
  - 不把 `/cmd_vel` 强行映射到旧 `0x0503` 云台自瞄控制包，避免误控。

当前真实 C 板旧协议没有上发底盘 `x/y/vx/vy/wz` 里程计，因此 bridge 不会伪造 `/odom`。后续若要接 Nav2 闭环，需要 C 板增加 Phase6 `ODOM` 文本帧，或新增等价 0xA5 二进制导航里程计帧。

## 当前限制

- 当前 C 板 active 代码还没有发送 Phase6 `ODOM / IMU / STAT` 文本导航帧；
- 当前 C 板 active 代码还没有接收 Phase6 `CMD / HB / STOP` 文本导航帧；
- 因此真实 `/odom`、`/imu/data`、底盘 `/cmd_vel` 闭环需要 C 板按 `docs/PHASE6_NAV_PROTOCOL_V1.md` 改造后做硬件验收；
- 本轮没有修改 RT-Thread 底盘 PID、安全闭环、Nav2 参数、slam_toolbox 参数、YOLO、语音或 Dashboard。

## 下一步人工验收

1. C 板实现 Phase6 文本帧或等价 0xA5 二进制导航帧；
2. 用 `scripts/phase6_mock_cboard.py` 先验证 ROS topic；
3. 接真实 C 板后检查 `/imu/data`、`/odom`、`odom -> base_link`；
4. 手动低速发布 `/cmd_vel`，确认 `vx/vy/wz` 方向；
5. 验证 `/cmd_vel` 超时、bridge 退出、通信线拔出、C 板急停时底盘停车；
6. 再回到 slam_toolbox 和 Nav2 基础联调。

## 2026-07-03：C 板 odom 与轻量 2D 建图追加交付

### 通信与 odom

- 实际导航通信统一使用 `standard_robot_pp_ros2`，不同时启动历史 `rtt_nav_bridge`。
- C 板 BCP `0x11` payload 为 36 字节：`vx/vy/wz/x/y/yaw` 各为 little-endian `int32`，缩放 10000。
- `/odom` 直接使用 C 板积分的 `x/y/yaw`，上位机不对速度再积分。
- 修正了校验失败仅在 debug 模式拒绝的问题，并增加严格帧长、有限值、位置/速度范围和动态单帧跳变检查。
- 增加 C 板坐标重置识别与刚体偏置，重置后保持 ROS `odom` 连续。
- `standard_robot_pp_ros2` 编译成功；5 项 BCP/odom 单元测试通过。
- 2026-07-04 实车确认 C 板上行符号为 `+x` 向后、`+y` 向右、`+yaw` 顺时针；新增上位机参数化六轴取反，转为 ROS REP-103。
- 坐标转换与原有校验/跳变/重置连续性测试合计 6/6 通过。

### RK3588 实机验收

- C 板重新上电后 `/odom` 稳定约 37–40 Hz，`/serial/imu` 可用。
- 120.006 秒静止监测收到 4646 帧，平均 38.715 Hz，0 非法帧，最大位置步长 0 m，最大单帧航向步长 0.0025 rad，结果 `PASS`。
- 静止 120 秒内航向累计变化约 0.109 rad；这不是跳变，但需由激光匹配/定位约束长时漂移。

### 轻量 2D 建图配置

- 继续使用现有六终端启动流程，不封装后台一键启停脚本。
- 保守参数直接写入 `~/livox_ws/config/mid360_to_scan.yaml` 和 `slam_toolbox_mid360.yaml`。
- `~/livox_ws/rviz/sentinel_nav_mapping.rviz` 已配置 `/map`、`/scan`、`/odom`、TF、SLAM markers，并增加可选 `/livox/lidar` 点云显示。
- 链路已打通：`/livox/lidar -> /scan -> slam_toolbox -> /map`。
- TF 已打通：`map -> odom -> base_link -> livox_frame`。
- `/livox/lidar` 和 `/scan` 实测约 10 Hz；120 个扫描桶的抽样帧中 97 个为有限测距。
- 保守参数：3°、4 m、队列 1、SLAM 0.15 m 分辨率、扫描降频 5、禁用回环。
- 单实例总内存约 130 MiB，`slam_toolbox` 约 4–5% 单核，未再出现 OOM。

### 仍需现场验收

- 低速前进、左移、左转，确认 ROS `+X/+Y/+yaw` 方向。
- 测量并修正 `base_link -> livox_frame` 真实外参；当前 `z=0.25 m`、其他为 0 仅是临时值。
- RViz 固定 `odom` 后慢速转动 30°–60°，确认静态墙体不随车体转动。
- 已知 C 板 USB CDC 限制保持不变：停止上位机通信后，再启动前需重插或重新上电 C 板。
