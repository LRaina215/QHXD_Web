# C++ IMU Backend Bridge 完成记录

完成日期：2026-07-03

## 目标与结果

`scripts/ros2_imu_bridge.py` 原本直接订阅约 770–790Hz `/serial/imu`。即使 HTTP 限制为 20Hz，`rclpy` 仍需处理全部回调；Mock 模式下还会每秒产生约 20 条 warning。实测 CPU 约 50–56%。

当前方案：

```text
/serial/imu (full rate, navigation preserved)
  -> standard_robot_pp_ros2 20Hz latest-sample mirror
  -> /serial/imu_backend
  -> imu_backend_bridge_node (C++)
  -> POST /api/internal/nuc/imu
  -> /ws/imu
```

合成 20Hz 输入下 C++ bridge 平均约 2% CPU。

## 主要修改

- `standard_robot_pp_ros2/src/imu_backend_bridge.cpp`：新增 rclcpp + libcurl bridge，最新帧单槽队列、独立 HTTP 工作线程、Mock 退避、日志限频。
- `standard_robot_pp_ros2/src/standard_robot_pp_ros2.cpp`：保留全速 `/serial/imu`，增加 20Hz `/serial/imu_backend`。
- `standard_robot_pp_ros2/config/standard_robot_pp_ros2.yaml`：增加 `backend_imu_rate_hz: 20.0`。
- `scripts/run_imu_bridge.sh`：统一启动 C++ / Python 实现。
- `scripts/switch_imu_bridge.sh`：运行时一键切换，不重启串口节点。
- `scripts/start_cboard_comm.sh`：默认 `cpp + /serial/imu_backend`。
- `scripts/status_public_robot.sh`：显示 bridge 实现与后端 IMU topic。

## 验收

- ROS 2 包 Release 编译成功。
- 新 C++ 文件单独 `ament_cpplint` 无问题。
- Mock 模式退避和日志限频正常。
- Real 模式下合成 IMU 成功写入 `/api/imu/latest`。
- Python 回退和 C++ 恢复均已实测。
- 后端、公网、YOLO 和视频服务的接口未修改。

## 回退

立即切换旧 Python bridge：

```bash
cd /home/robomaster/QHXD
./scripts/switch_imu_bridge.sh python
```

持久回退：

```env
ROS2_IMU_BRIDGE_IMPL=python
ROS2_IMU_TOPIC=/serial/imu_backend
ROS2_IMU_BRIDGE_RATE_HZ=20
```

完整源码备份：

```text
/home/robomaster/QHXD_backups/imu_bridge_20260703_120420.tar.gz
```
