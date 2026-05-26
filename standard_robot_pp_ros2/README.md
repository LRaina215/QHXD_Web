# standard_robot_pp_ros2

RK3588 上用于上下位机串口通信的 ROS 2 Humble 包。当前版本保留主通信节点 `standard_robot_pp_ros2_node`，通过 BCP 串口协议和下位机通信；已移除原工程中不参与当前通信链路、且在本机接口依赖不匹配的云台管理桥接、auto_aim 跟踪订阅、机器人描述/RViz 启动项。

## 功能

- 读取下位机 BCP 帧并发布 IMU、底盘里程、云台关节、裁判系统相关话题。
- 订阅 ROS 控制话题并下发底盘、云台、发射机构控制帧。
- 串口断开或长时间收不到合法帧时自动重连。
- 支持调试话题 `serial/debug/*`，通过参数 `debug:=true` 开启。

## 依赖

- Ubuntu 22.04
- ROS 2 Humble
- `pb_rm_interfaces`
- `ros-humble-serial-driver`
- `ros-humble-asio-cmake-module`

如果从空工作区构建，先导入接口依赖：

```bash
cd ~/QHXD
vcs import . < standard_robot_pp_ros2/dependencies.repos
```

在本 RK3588 上已安装：

```bash
sudo apt-get install -y ros-humble-serial-driver ros-humble-asio-cmake-module
```

## 编译

```bash
cd ~/QHXD
source /opt/ros/humble/setup.bash
colcon build --packages-up-to standard_robot_pp_ros2 --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo
source install/setup.bash
```

本机验证命令：

```bash
colcon build --packages-select standard_robot_pp_ros2 --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo
ros2 pkg executables standard_robot_pp_ros2
```

期望可执行文件：

```text
standard_robot_pp_ros2 standard_robot_pp_ros2_node
```

## 启用通信

默认参数文件为 `config/standard_robot_pp_ros2.yaml`，默认串口为 `/dev/ttyCBoard`，波特率 `115200`。

```bash
cd ~/QHXD
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py
```

如果当前没有配置 udev，但下位机枚举为 `/dev/ttyACM0` 或 `/dev/ttyUSB0`，可以临时覆盖串口参数：

```bash
ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py \
  params_file:=/home/robomaster/QHXD/standard_robot_pp_ros2/config/standard_robot_pp_ros2.yaml \
  --ros-args -p device_name:=/dev/ttyACM0
```

更推荐配置 udev，使 C 板稳定映射到 `/dev/ttyCBoard`：

```bash
cd ~/QHXD/standard_robot_pp_ros2
./script/create_udev_rules.sh
```

## 常用话题

订阅并下发给下位机：

| 话题 | 类型 | 说明 |
| --- | --- | --- |
| `cmd_vel` | `geometry_msgs/msg/Twist` | 底盘速度控制。代码内已做 ROS 坐标到当前底盘约定的映射。 |
| `cmd_gimbal_joint` | `sensor_msgs/msg/JointState` | 云台目标，使用 `gimbal_pitch_joint`、`gimbal_yaw_joint`。 |
| `cmd_shoot` | `std_msgs/msg/UInt8` | 发射控制值，按下位机约定解释。 |

发布给上层：

| 话题 | 类型 | 说明 |
| --- | --- | --- |
| `serial/imu` | `sensor_msgs/msg/Imu` | 下位机 IMU 或云台回退姿态。 |
| `serial/receive` | `geometry_msgs/msg/Vector3` | 调试用 yaw/pitch/roll。 |
| `serial/gimbal_joint_state` | `sensor_msgs/msg/JointState` | 云台关节状态。 |
| `serial/robot_motion` | `geometry_msgs/msg/Twist` | 底盘回传运动信息。 |
| `referee/game_status` | `pb_rm_interfaces/msg/GameStatus` | 比赛状态。 |
| `referee/all_robot_hp` | `pb_rm_interfaces/msg/GameRobotHP` | 全机器人血量。 |
| `referee/event_data`、`referee/rfid_status`、`referee/robot_status`、`referee/buff` | `pb_rm_interfaces` | 兼容保留的裁判系统状态。 |

## 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `device_name` | `/dev/ttyCBoard` | 串口设备路径。 |
| `baud_rate` | `115200` | 串口波特率。 |
| `flow_control` | `none` | 串口流控。 |
| `parity` | `none` | 校验位。 |
| `stop_bits` | `1` | 停止位。 |
| `debug` | `false` | 开启后发布 `serial/debug/*`。 |
| `bcp_d_addr` | `3` | 发送帧目标地址。 |
| `bcp_rx_addr` | `1` | 接收帧本机地址。 |
| `bcp_gimbal_ctrl_mode` | `1` | 下发云台控制模式。 |
| `bcp_default_bullet_vel` | `15` | 发射机构默认弹速字段。 |
| `bcp_default_remain_bullet` | `0` | 发射机构默认剩余弹量字段。 |

## RK3588 验证记录

2026-05-26 在 `100.113.173.115` 上已完成验证：

```bash
ls -l /dev/ttyCBoard /dev/ttyACM0
ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py
ros2 topic echo /serial/imu --once
ros2 topic hz /serial/imu
ros2 topic echo /serial/receive --once
```

结果：`/dev/ttyCBoard` 已映射到 `/dev/ttyACM0`，`/serial/imu` 可收到 C 板 IMU 数据，短时间观测频率约 `999 Hz`，`/serial/receive` 可收到 yaw/pitch/roll 调试数据。

## 注意事项

- 启动前确认用户在 `dialout` 组内，或 udev 规则已给串口权限；否则节点会反复打开串口失败。
- 已在当前 RK3588 上创建 udev 规则：`/dev/ttyCBoard -> /dev/ttyACM0`。若更换 C 板或串口号变化，重新运行 `./script/create_udev_rules.sh` 后用 `ls -l /dev/ttyCBoard` 确认映射。
- 下位机帧头为 `0xFF`，地址需要与 `bcp_rx_addr`、`bcp_d_addr` 对齐。地址不匹配会丢帧。
- 启动后超过初始宽限期仍收不到合法 BCP 帧，节点会自动关闭并重开串口。
- 原 `cmd_gimbal -> gimbal_manager -> cmd_gimbal_joint` 桥接已删除；上层如需控制云台，请直接发布 `cmd_gimbal_joint`。
