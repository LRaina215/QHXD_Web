# standard_robot_pp_ros2 导航通信启动说明

`standard_robot_pp_ros2` 是当前 RK3588 与 C 板通信的正式 ROS 2 包。导航链路请使用这个包，不要再启动旧的 `rtt_nav_bridge`，否则两个节点会抢占 `/dev/ttyACM0` / `/dev/ttyCBoard`。

## 当前功能

- 打开 C 板 USB CDC 串口，默认设备 `/dev/ttyCBoard`，当前映射到 `/dev/ttyACM0`。
- 通过 BCP 协议接收下位机数据。
- 发布 IMU、底盘运动、云台状态和裁判系统话题。
- 保留全速 `/serial/imu` 给导航，另外生成 20Hz `/serial/imu_backend` 供后端状态桥接。
- 默认使用 C++ IMU backend bridge，通过现有 HTTP API 和 WebSocket 刷新前端。
- 将下位机上发的底盘速度 `serial/robot_motion` 积分为标准导航话题 `/odom`。
- 可选发布 `odom -> base_link` TF，默认开启。
- 订阅 `/cmd_vel` 并向下位机发送底盘控制帧。

## 依赖

系统环境：

- Ubuntu 22.04
- ROS 2 Humble
- C 板枚举为 USB CDC ACM 设备

ROS 包依赖：

- `rclcpp`
- `rclcpp_components`
- `serial_driver`
- `asio_cmake_module`
- `geometry_msgs`
- `nav_msgs`
- `sensor_msgs`
- `std_msgs`
- `std_srvs`
- `tf2_ros`
- `tf2_geometry_msgs`
- `pb_rm_interfaces`
- `libcurl4-openssl-dev`

当前 RK3588 上编译已通过，未发现缺少新的系统依赖。如从新系统部署，可先安装：

```bash
sudo apt-get update
sudo apt-get install -y \
  libcurl4-openssl-dev \
  ros-humble-serial-driver \
  ros-humble-asio-cmake-module \
  ros-humble-nav-msgs \
  ros-humble-tf2-ros \
  ros-humble-tf2-geometry-msgs
```

## 编译

```bash
cd ~/QHXD
source /opt/ros/humble/setup.bash
colcon build --packages-up-to standard_robot_pp_ros2 --symlink-install   --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo
source install/setup.bash
```

只重编通信包：

```bash
cd ~/QHXD
source /opt/ros/humble/setup.bash
colcon build --packages-select standard_robot_pp_ros2 --symlink-install
source install/setup.bash
```

## 启动

先确认没有旧通信节点占用串口：

```bash
pkill -f rtt_nav_bridge_node || true
pkill -f standard_robot_pp_ros2_node || true
pkill -f 'ros2 launch standard_robot_pp_ros2' || true
lsof /dev/ttyACM0 2>/dev/null || true
lsof /dev/ttyCBoard 2>/dev/null || true
```

确认设备：

```bash
ls -l /dev/ttyCBoard /dev/ttyACM0
```

启动通信节点：

```bash
cd ~/QHXD
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py
```

默认参数在：

```text
standard_robot_pp_ros2/config/standard_robot_pp_ros2.yaml
```

关键参数：

```yaml
device_name: /dev/ttyCBoard
baud_rate: 115200
publish_odom: true
publish_odom_tf: true
cboard_odom_invert_x: true
cboard_odom_invert_y: true
cboard_odom_invert_yaw: true
odom_frame_id: odom
base_frame_id: base_link
backend_imu_rate_hz: 20.0
bcp_d_addr: 3
bcp_rx_addr: 1
```

## 导航相关话题

上层控制输入：

| 话题 | 类型 | 说明 |
| --- | --- | --- |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | 导航栈底盘速度命令，节点会打包下发给 C 板。 |

下位机上行与导航输出：

| 话题 | 类型 | 说明 |
| --- | --- | --- |
| `/serial/robot_motion` | `geometry_msgs/msg/Twist` | 下位机上发底盘速度。 |
| `/serial/imu` | `sensor_msgs/msg/Imu` | 下位机 IMU 或姿态数据。 |
| `/serial/imu_backend` | `sensor_msgs/msg/Imu` | 最新 IMU 的 20Hz 后端专用镜像，不替代导航原始话题。 |
| `/odom` | `nav_msgs/msg/Odometry` | 直接使用 C 板 `0x11` 帧中的 `x/y/yaw`；上位机不再对速度积分。 |
| `/tf` | `tf2_msgs/msg/TFMessage` | 默认发布 `odom -> base_link`。 |

其他保留话题包括 `/serial/gimbal_joint_state`、`/serial/receive`、`/serial/robot_state_info` 和 `/referee/*`。

## 验证命令

启动节点后，在另一个终端执行：

```bash
cd ~/QHXD
source /opt/ros/humble/setup.bash
source install/setup.bash

ros2 topic list | sort | grep -E '^/(odom|tf|serial/robot_motion|serial/imu|serial/imu_backend|cmd_vel)'
ros2 topic info -v /odom
ros2 topic echo /serial/robot_motion --once
ros2 topic echo /odom --once
ros2 topic echo /tf --once
ros2 topic hz /odom
ros2 topic hz /serial/imu_backend
```

## IMU 后端桥接

默认链路：

```text
C 板 -> /serial/imu (全速)
     `-> /serial/imu_backend (20Hz)
         -> imu_backend_bridge_node (C++)
         -> POST /api/internal/nuc/imu
         -> /ws/imu -> Dashboard
```

C++ bridge 的 ROS 回调只保留最新样本，HTTP 由独立工作线程执行，最多积压一帧。后端处于 Mock 模式时会退避 2 秒，重复日志限频为 5 秒。

```bash
cd ~/QHXD
./scripts/switch_imu_bridge.sh cpp
./scripts/switch_imu_bridge.sh python
./scripts/status_public_robot.sh
```

默认与持久回退配置：

```env
ROS2_IMU_BRIDGE_IMPL=cpp
ROS2_IMU_TOPIC=/serial/imu_backend
ROS2_IMU_BRIDGE_RATE_HZ=20
```

将 `ROS2_IMU_BRIDGE_IMPL` 改为 `python` 即可在下次开机继续使用旧 Python bridge。原文件 `scripts/ros2_imu_bridge.py` 未删除。

本次改造前的完整备份：

```text
/home/robomaster/QHXD_backups/imu_bridge_20260703_120420.tar.gz
```

如果 `/odom` topic 存在但 `echo --once` 长时间没有输出，说明 ROS 侧 publisher 已创建，但还没有收到下位机有效底盘运动帧。继续做原始串口检查：

```bash
pkill -f standard_robot_pp_ros2_node || true
stty -F /dev/ttyACM0 115200 raw -echo -crtscts
timeout 4 dd if=/dev/ttyACM0 bs=1 count=128 2>/tmp/dd_serial_err | xxd -g1 -c16
cat /tmp/dd_serial_err
```

- 能看到以 BCP 帧头开头的字节流：优先检查 `bcp_rx_addr` / `bcp_d_addr` 是否与下位机一致。
- 完全没有字节：问题不在 ROS 解析层，需要检查下位机是否正在持续上发、是否需要先收到启动帧、USB CDC 是否进入发送状态。

## 2026-07-03 实测记录

- 优化前 Python bridge 直接订阅约 770–790Hz `/serial/imu`，平均约 50–56% CPU。
- C++ bridge 直接订阅全速话题时约 18.8% CPU，仅换语言不足以完全解决问题。
- 增加 20Hz `/serial/imu_backend` 后，C++ bridge 在合成 20Hz 输入下平均约 2% CPU。
- Real 模式合成验收成功，`/api/imu/latest` 收到完整姿态、角速度和加速度。
- Mock 模式会退避且限频日志，不再每秒写入约 20 条 warning。
- Python 回退和再切回 C++ 均已实际执行成功。
- 本次重启串口节点后 C 板未继续上发真实 IMU/odom；这一硬件项不阻塞合成桥接验收。

### C 板 odom 导航加固

- `0x11` 帧必须是 36 字节 payload，校验、帧长或数值范围异常时直接丢弃。
- `/odom` 直接发布 C 板位姿，仅在 C 板重置坐标时施加刚体偏置以保持 `odom` 连续。
- 已增加 `nan/inf`、绝对位置、速度、单帧位置跳变和航向跳变拦截。
- 120 秒静止验收：4646 帧，38.715 Hz，0 非法帧，最大位置步长 0 m，最大单帧航向步长 0.0025 rad。
- 2026-07-04 实车确认 C 板上行符号为 `+x` 向后、`+y` 向右、`+yaw` 顺时针；上位机在异常过滤前同时取反 `x/y/yaw` 和 `vx/vy/wz`，转为 ROS REP-103。
- 三个 `cboard_odom_invert_*` YAML 参数可独立关闭，不需要再改 C 板固件。

`colcon test` 当前会把包目录内的历史 `build/` / `install/` 生成文件一并纳入 lint，因此全包 lint 仍有既有失败；新增 `imu_backend_bridge.cpp` 已单独通过 `ament_cpplint`。

## 注意事项

- 不要同时启动 `rtt_nav_bridge` 和 `standard_robot_pp_ros2`。
- 不要同时开多个 `standard_robot_pp_ros2_node`，否则会抢同一个串口。
- 如果只杀 `ros2 launch` 父进程，子节点可能仍占用串口；建议用 `pkill -f standard_robot_pp_ros2_node` 清理。
- 若更换 C 板或串口号变化，重新检查 `/dev/ttyCBoard` 映射。
- 当前 C 板 USB CDC 已知限制：停止上位机通信后，再启动前需重插或重新上电 C 板。
- `/odom` 位姿来自 C 板直接上发；不要同时启动另一个速度积分 odom 节点。
# Point-LIO navigation mode

When Point-LIO is selected as the navigation odometry front end, this package
must continue handling serial communication and `/cmd_vel`, but it must not
publish a competing odometry topic or TF. Use a dedicated parameter file (or
equivalent launch overrides) with:

```yaml
publish_odom: false
publish_odom_tf: false
```

Only one component may publish `odom -> base_link`. Keep both values `true`
only when intentionally testing the C-board odometry without Point-LIO.
