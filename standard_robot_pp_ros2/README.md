# standard_robot_pp_ros2 导航通信启动说明

`standard_robot_pp_ros2` 是当前 RK3588 与 C 板通信的正式 ROS 2 包。导航链路请使用这个包，不要再启动旧的 `rtt_nav_bridge`，否则两个节点会抢占 `/dev/ttyACM0` / `/dev/ttyCBoard`。

## 当前功能

- 打开 C 板 USB CDC 串口，默认设备 `/dev/ttyCBoard`，当前映射到 `/dev/ttyACM0`。
- 通过 BCP 协议接收下位机数据。
- 发布 IMU、底盘运动、云台状态和裁判系统话题。
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

当前 RK3588 上编译已通过，未发现缺少新的系统依赖。如从新系统部署，可先安装：

```bash
sudo apt-get update
sudo apt-get install -y   ros-humble-serial-driver   ros-humble-asio-cmake-module   ros-humble-nav-msgs   ros-humble-tf2-ros   ros-humble-tf2-geometry-msgs
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
odom_frame_id: odom
base_frame_id: base_link
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
| `/odom` | `nav_msgs/msg/Odometry` | 由 `/serial/robot_motion` 积分生成，供导航栈使用。 |
| `/tf` | `tf2_msgs/msg/TFMessage` | 默认发布 `odom -> base_link`。 |

其他保留话题包括 `/serial/gimbal_joint_state`、`/serial/receive`、`/serial/robot_state_info` 和 `/referee/*`。

## 验证命令

启动节点后，在另一个终端执行：

```bash
cd ~/QHXD
source /opt/ros/humble/setup.bash
source install/setup.bash

ros2 topic list | sort | grep -E '^/(odom|tf|serial/robot_motion|serial/imu|cmd_vel)'
ros2 topic info -v /odom
ros2 topic echo /serial/robot_motion --once
ros2 topic echo /odom --once
ros2 topic echo /tf --once
ros2 topic hz /odom
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

## 本次实测记录

时间：2026-05-26 17:43 左右，设备 `100.113.173.115`。

已完成：

- `standard_robot_pp_ros2` 可打开 `/dev/ttyCBoard -> /dev/ttyACM0`。
- `colcon build --packages-select standard_robot_pp_ros2 --symlink-install` 编译通过。
- `/odom` publisher 已补齐并出现在 `ros2 topic list`。
- `/tf` publisher 已补齐并出现在 `ros2 topic list`。
- `ros2 topic info -v /odom` 显示 publisher 为 `standard_robot_pp_ros2`。

当前未通过：

- `ros2 topic echo /odom --once` 没有收到实际消息。
- `ros2 topic hz /serial/robot_motion`、`/serial/imu`、`/odom` 均未测到频率。
- 原始串口抓包 `timeout 4 dd if=/dev/ttyACM0 ...` 没有读到字节。
- 节点日志持续出现 `No valid BCP frame for 12002 ms, forcing serial reopen.`。

结论：ROS 侧导航 odom 出口已经补齐；当前真机链路卡在 C 板 USB CDC 上行没有持续吐出有效 BCP 数据。下位机需要确认持续上发 chassis odom / IMU，或者确认上位机是否需要发送特定启动帧后才开始上发。

## 注意事项

- 不要同时启动 `rtt_nav_bridge` 和 `standard_robot_pp_ros2`。
- 不要同时开多个 `standard_robot_pp_ros2_node`，否则会抢同一个串口。
- 如果只杀 `ros2 launch` 父进程，子节点可能仍占用串口；建议用 `pkill -f standard_robot_pp_ros2_node` 清理。
- 若更换 C 板或串口号变化，重新检查 `/dev/ttyCBoard` 映射。
- `/odom` 由底盘速度积分得到，启动时位姿从 `(0, 0, 0)` 开始；后续如有绝对定位或轮式里程计位姿帧，可再替换为下位机直接上发位姿。
