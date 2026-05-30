# PHASE6_DONE

日期：2026-05-26
设备：RK3588 `100.113.173.115`
工作目录：`/home/robomaster/QHXD/standard_robot_pp_ros2`

## 完成内容

- 阅读并梳理 `standard_robot_pp_ros2` 主通信代码、配置、launch 和依赖关系。
- 在 RK3588 上补齐构建依赖：`ros-humble-serial-driver`、`ros-humble-asio-cmake-module`。
- 通过 `vcs import` 拉取并构建 `pb_rm_interfaces`；排查阶段临时拉取的 `auto_aim_interfaces`、`pb2025_robot_description` 已在清理后删除。
- 删除或移除当前上下位机 BCP 通信链路未使用且导致 RK3588 编译失败的内容：
  - `src/gimbal_manager.cpp`
  - `include/standard_robot_pp_ros2/gimbal_manager.hpp`
  - `launch/__pycache__/standard_robot_pp_ros2.launch.cpython-310.pyc`
  - `auto_aim_interfaces/msg/Target` 订阅和 `tracking` 缓存字段
  - `gimbal_manager_node` 组件注册与 launch 启动项
  - 旧 launch 中 `pb2025_robot_description`、`nav2_common`、`joint_state_publisher`、`robot_state_publisher` 相关启动逻辑
  - 过期迁移文档：`CODEX_POINTCLOUD_NAV_INVESTIGATION.md`、`COMM_CONTRACT.md`、`COMM_MAPPING.md`、`NOTDEFINE.md`、`TARGET_ENV_CHECKLIST.md`、`TODOANDDONE.md`
  - 包目录内误生成的 `build/`、`install/`、`log/` 构建产物
- 将调试和射击消息从未安装的 `example_interfaces` 切换为本机已有的 `std_msgs`。
- 将 CMake 从 `DIRECTORY src` 改为显式编译当前需要的源文件，避免误把未使用源码编入目标。
- 精简 `dependencies.repos`，当前仅保留 `pb_rm_interfaces`。
- 更新 `README.md`，写入编译、启用通信方法、话题、参数和注意事项。

## 验证结果

执行命令：

```bash
cd ~/QHXD
source /opt/ros/humble/setup.bash
source install/setup.bash
colcon build --packages-select standard_robot_pp_ros2 --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo
ros2 pkg executables standard_robot_pp_ros2
ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py --show-args
```

结果：

```text
Summary: 1 package finished
standard_robot_pp_ros2 standard_robot_pp_ros2_node
launch arguments: params_file, use_respawn, log_level
```

## 当前注意事项

- 当前 RK3588 已创建 `/dev/ttyCBoard -> ttyACM0` udev 映射，可直接使用默认 `device_name: /dev/ttyCBoard`。
- `apt-get update` 遇到 `packages.ros.org` 公钥缺失告警，但 USTC ROS 镜像可用，本次依赖安装和构建已完成。
- `gimbal_manager` 已删除；云台控制入口改为直接发布 `cmd_gimbal_joint`。

## udev 与 IMU 接收验证

日期：2026-05-26

- 查看 `/dev/ttyACM0` 的 udev 属性，确认 C 板属性为 `idVendor=0ffe`、`idProduct=0001`、`serial=32021919830108`。
- 执行 `bash ./script/create_udev_rules.sh` 创建 `/etc/udev/rules.d/99-RoboMaster_C_Board.rules`。
- 重新触发当前设备后确认映射生效：`/dev/ttyCBoard -> ttyACM0`，权限为 `crw-rw-rw- root dialout`。
- 启动 `ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py` 后，节点日志显示 `Serial port opened!`。
- `ros2 topic echo /serial/imu --once` 成功收到 IMU 消息，返回码 `0`。
- `ros2 topic hz /serial/imu` 短时间观测约 `999 Hz`。
- `ros2 topic echo /serial/receive --once` 成功收到 yaw/pitch/roll：`x=-56.274, y=-32.109, z=-0.01`。

## 通信节点重启问题排查与修复

日期：2026-05-26

### 复现结果

- 在 RK3588 上启动一次 `ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py` 后，节点可打开 `/dev/ttyCBoard`。
- 只杀掉 `ros2 launch` 父进程时，实际 `standard_robot_pp_ros2_node` 会残留为 PPID 1 的孤儿进程并继续持有 `/dev/ttyCBoard`。
- 再次启动 launch 时，第二个节点也能打开同一个 CDC 串口，两个进程会同时读同一设备，导致 IMU 数据被抢走或无法解析。
- 清理所有上位机节点后，直接裸读 `/dev/ttyCBoard` 未读到任何原始字节；重新 bind `cdc_acm` 后设备节点恢复，但仍无原始字节，说明当前板端发送/USB CDC 状态也存在问题，单靠上位机重启不能完全恢复。

### 上位机修复

- 在 `standard_robot_pp_ros2` 中增加串口进程锁：同一 `device_name` 只允许一个 `standard_robot_pp_ros2_node` 持有。
- 增加 BCP 心跳帧发送：每 100 ms 发送 `ID=0xF0`、payload `1` 的心跳帧，避免没有控制输入时下位机 500 ms 心跳超时。
- 重新编译验证通过：

```bash
cd ~/QHXD/standard_robot_pp_ros2
source /opt/ros/humble/setup.bash
source install/setup.bash
colcon build --packages-select standard_robot_pp_ros2 --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo
```

结果：`Summary: 1 package finished`。

### 上位机验证

- 第一个节点启动后占用 `/dev/ttyCBoard`。
- 第二个节点重复启动时，子进程退出并提示：`Serial device /dev/ttyCBoard is already owned by another standard_robot_pp_ros2 process`。
- 清理所有 ROS2 通信节点后，`fuser -v /dev/ttyCBoard` 无占用。

### 下位机代码风险点

- `/Users/lraina/Documents/RM-Vis/AutoAim/rm/src/task/transmission/transmission_task.c`：未收到心跳时每 500 ms 关闭并重新打开 `vcom`，会与高频 `rt_device_write` 发送任务交织，主机关闭/重开节点时容易把 USB CDC 状态打乱。
- `/Users/lraina/Documents/RM-Vis/AutoAim/rm/rt-thread/components/drivers/usb/usbdevice/class/cdc_vcom.c`：`CDC_SET_CONTROL_LINE_STATE` 固定 `data->connected = 1`，忽略主机关闭串口时的 DTR=0，可能导致 C 板误以为主机仍连接，继续向不可用端点高频写入并触发 TX timeout。
- `/Users/lraina/Documents/RM-Vis/AutoAim/rm/src/task/transmission/transmission_task.c`：接收回调固定取 `sizeof(RpyTypeDef)` 并只检查帧头，没有按 `LEN` 和校验恢复同步，异常/短帧时容易误解析。

### 后续建议

- 下位机将 `data->connected = 1` 改为根据 `setup->wValue & 0x01` 设置连接状态。
- 下位机不要在心跳超时路径里高频 close/open `vcom`；建议只标记上位机离线、停止使用上位机控制量，并继续允许 CDC 接收新心跳恢复。
- 修改并烧录 C 板后，再执行裸串口和 ROS2 IMU 复测。

## Ctrl+C 重启后无数据复测

日期：2026-05-26

- 已将顶层工作区 `~/QHXD/install` 重新编译，确保从 `~/QHXD` 启动时使用包含串口锁和 BCP 心跳的新上位机节点。
- 复测现象：通信节点可以打开 `/dev/ttyCBoard`，但 `/serial/imu` 与 `/serial/receive` 均无消息，节点日志持续出现 `No valid BCP frame for 12003 ms`。
- 清理全部上位机节点后，`fuser -v /dev/ttyCBoard` 无占用；此时直接裸读 `/dev/ttyCBoard` 仍为 0 字节。
- 对 C 板 USB 设备执行完整 authorized 0/1 重新枚举后，`/dev/ttyCBoard -> ttyACM0` 恢复，但裸读仍为 0 字节。
- 结论：当前无数据不是 ROS2 topic 或串口占用问题，而是 C 板固件侧 USB CDC/发送任务已停止输出，需要烧录下位机修复后的固件或物理复位 C 板。
- 已在本地电控源码 `/Users/lraina/Documents/RM-Vis/AutoAim/rm` 中做最小修复：CDC DTR 断开时正确置 `connected=false` 并清 TX 缓冲；心跳超时不再反复 close/open `vcom`，只标记上位机离线。
