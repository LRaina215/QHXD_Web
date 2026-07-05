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

## 2026-07-04：Point-LIO 前端里程计与 2D 接口部署

### 部署范围

- Point-LIO 继续固定为北极熊 ROS 2 分支提交
  `e85e79558cf746f6699888a54285fe48b3b0ac71`。
- 从北极熊 `pb2025_sentry_nav` 提交
  `12aadbb8950c107153af80586e151172747d612b` 仅引入
  `loam_interface` 与 `sensor_scan_generation`，未复用其余导航栈。
- 新增 `~/livox_ws/launch/point_lio_interfaces.launch.py`，将 Point-LIO 输出转换为
  `/odometry`、`/sensor_scan` 和动态 `odom -> base_link`。
- Point-LIO 配置启用 `/cloud_registered`，供接口链路使用。
- 新增 `standard_robot_pp_ros2_pointlio.yaml`：保留串口和 `/serial/imu`，仅关闭
  C 板 `/odom` 与 `odom -> base_link`，防止双 TF 发布者。
- `sentinel_nav_mapping.rviz` 已切换显示 `/odometry` 与 `/sensor_scan`，并保持
  里程计箭头 `Keep: 1`，避免历史箭头堆叠。

### RK3588 编译与静态验收

- `loam_interface`、`sensor_scan_generation` 在 Ubuntu 22.04、ROS 2 Humble、
  RK3588 ARM64 上编译成功。
- 实机雷达静止测试时，下列话题均约 10 Hz：
  `/aft_mapped_to_init`、`/cloud_registered`、`/lidar_odometry`、
  `/registered_scan`、`/odometry`、`/sensor_scan`。
- `/odometry` 正确输出 `frame_id=odom`；隔离测试中的
  `child_frame_id=point_lio_base_test`。
- `/sensor_scan` 正确输出 `frame_id=livox_frame`，抽样帧宽度 320 点。
- `/sensor_scan -> pointcloud_to_laserscan -> /scan` 静态验收通过，`/scan`
  约 9.92 Hz；120 个角度桶中抽样有 49 个有限值，范围约 0.94--3.91 m。
- 隔离测试 TF `odom -> point_lio_base_test` 可连续查询，未与当前 C 板
  `odom -> base_link` 冲突。
- 资源抽样：Livox 驱动约 52% 单核/43 MB RSS，Point-LIO 约 26%/87 MB，
  两个接口节点合计约 8%/62 MB。
- 测试结束后已停止所有临时雷达、Point-LIO、静态 TF 和接口进程；原 C 板通信
  PID 22713 保持运行。

### 尚需人工实车验收

- 按 README 切换到 Point-LIO 通信参数；该操作需要用户配合重插或重新上电 C 板。
- 测量真实 `base_link -> livox_frame` 外参，替换临时 `z=0.25 m`。
- 完成静止漂移、直行、左移、逆时针旋转方向测试。
- 将 `/sensor_scan` 转为 `/scan`，确认 RViz 中静态环境不随车体运动。
- 最后接入现有 `slam_toolbox`，验收完整
  `map -> odom -> base_link -> livox_frame` 单链 TF，再开始低速建图与 Nav2 联调。

## 2026-07-04：建图验收与 Nav2 静态部署

### 建图现场验收

- 用户确认优化后的 0.05 m 地图无明显双墙或整体偏移；
- 返回起点后，RViz 中位置与建图起点近乎重合；
- 连续运行约 5--6 分钟，Point-LIO、TF 和地图均无明显异常；
- `sentinel_map.yaml/.pgm/.posegraph/.data` 已完整保存。

结论：Point-LIO 前端里程计与 slam_toolbox 建图阶段验收通过。

### Nav2 部署

- 新增标准 ROS 2 包 `~/livox_ws/src/rk3588_navigation`；
- 提供 `localization.launch.py`、`navigation.launch.py`、`bringup.launch.py`；
- AMCL 使用 `nav2_amcl::OmniMotionModel`，接收 `/scan` 并发布
  `map -> odom`；Point-LIO interfaces 继续独占 `odom -> base_link`；
- DWB 配置为全向底盘，初始限速 X=0.25 m/s、Y=0.20 m/s、
  Nav2 默认不旋转底盘；
- 参考本车旧仓库 `LRaina215/HNU_NHS_SENTRY_UP` 的最新实车参数，迁移
  Theta*、全向平移、忽略最终 yaw、取消 RotateToGoal 和 DWB critic 权重；
- 旧配置中的 20 m/s 与 0.23 m 半径未直接迁移，继续使用当前 SI 低速和
  0.32 m 保守半径；
- 使用 Theta* 全局规划、ObstacleLayer + InflationLayer 两级代价地图；
- 临时 `robot_radius=0.32 m`，必须由现场按真实外廓复核；
- 使用不含自动后退/旋转恢复的 NavigateToPose BT，初测失败时直接停止；
- RViz 目标工具切换为 `nav2_rviz_plugins/GoalTool`。

### 隔离域软件验收

- `rk3588_navigation` 在 RK3588/ROS 2 Humble 编译成功；
- `sentinel_map` 加载为 209 x 261、0.05 m/cell；
- map_server、AMCL、controller、planner、smoother、behavior、BT navigator、
  waypoint follower、velocity smoother 均成功激活；
- 全向 DWB、Theta*、局部/全局 costmap 插件全部加载成功；
- `/navigate_to_pose`、`/compute_path_to_pose`、`/follow_path` action 可用；
- Theta* 在已知自由区 (0.3,3.3) 到 (1.2,3.3) 静态规划成功，耗时约 2.6 ms；
- 空闲 3 s 无 `/cmd_vel` 输出；测试使用 ROS_DOMAIN_ID=99，未控制真实底盘；
- 合并启动改为先激活定位、延时 4 秒再启动导航，消除 Humble lifecycle 并发竞态；
- 真实 ROS 域 localization launch 已激活并收到当前 `/scan`，仅等待用户设置实际
  初始位姿；临时定位实例随后已停止；
- 隔离测试进程已全部停止，用户当前 Point-LIO/建图链路未被中断。

### 剩余现场验收

- 停止 mapping slam_toolbox 后启动 AMCL，设置初始位姿并验证激光贴图；
- 实测车体外廓并修正 footprint/robot radius；
- 先进行 0.3--0.5 m 短目标，再测试障碍物、取消目标和停车安全；
- 验证 Ctrl-C、命令超时、通信异常和硬件急停均能可靠停车；
- 依据实车轨迹调整 DWB、inflation 和最终速度上限。

## 2026-07-04：开机 C 板通信切换为 Point-LIO 模式

- 定位到旧串口占用来自 `qhxd-boot.service` 启动的默认通信 launch；旧 launch
  使用默认 `use_respawn=True`，仅结束 node 后会自动重启并继续占用串口。
- 修改 `scripts/start_cboard_comm.sh`，默认加载
  `standard_robot_pp_ros2_pointlio.yaml` 并传入 `use_respawn:=false`。
- 新增 `CBOARD_PARAMS_FILE`、`CBOARD_USE_RESPAWN` 环境变量，可由 `.env` 覆盖。
- 启动脚本会检查参数文件存在，并在日志中输出实际 params file 与 respawn 设置。
- `qhxd-boot.service` 保持 enabled；unit 文件未变化，不需要 daemon-reload，后续重启
  RK3588 会自动按 Point-LIO 模式启动 C 板通信。
- 已清理旧 launch PID 2636 与串口 node PID 3324；`/dev/ttyCBoard` 当前无占用。
- 当前固件限制不变：通信停止后，重新启动前仍需重插或重新上电 C 板。

## 2026-07-04：RViz Nav2 Goal 修正

- 排查“点击 Nav2 Goal 无路径、实车不动”：AMCL、`map -> base_link`、地图、
  costmap、Theta* 与 Nav2 lifecycle 均正常，但旧 `/rviz` 节点没有
  `/navigate_to_pose` action client，目标从未进入 BT Navigator。
- 根因是 RViz 配置只有 `nav2_rviz_plugins/GoalTool`，缺少与其配套的
  `nav2_rviz_plugins/Navigation 2` 面板；GoalTool 本身不发送 action。
- 已在 `sentinel_nav_mapping.rviz` 增加 Navigation 2 面板。
- 临时启动修复后的 RViz 验证，`/rviz_goal_test` 正确创建
  `/navigate_to_pose` action client；测试 RViz 随后已停止。
- 在真实定位和地图上调用仅规划的 `ComputePathToPose`，Theta* 从当前位姿到
  `(0.55, 0.25)` 成功生成路径，耗时约 12 ms，未向底盘发送速度。
- RK3588 的 `active samplers with a different type` GLSL 日志不影响地图显示、
  action 或路径规划。

## 2026-07-04 Nav2 平移速度调整

- DWB 的 X/Y 搜索范围保持 `-20.0 ~ +20.0`，合平移速度范围设为
  `0.50 ~ 20.0`，保证其非零平移候选速度不低于 0.50；
- 真正发送 C 板的 `/cmd_vel` 由 `velocity_smoother` 限制，X/Y 分量范围为
  `-0.50 ~ +0.50 m/s`；修复旧 smoother 将输出截在 X=0.25、Y=0.20 的问题；
- smoother 的 X/Y 加减速度改为 `±10.0 m/s^2`，在 20 Hz 下一个周期即可达到
  0.50 m/s，避免加速阶段持续输出底盘无法执行的约 0.20 m/s 指令；
- 参数已同步写入磁盘和当前运行节点。修改后只需重启 `navigation.launch.py`，
  无需重启 Point-LIO、AMCL 或雷达前端；
- 首次实车验收使用 0.3~0.5 m 短目标并准备急停，同时观察最终 `/cmd_vel`，而非
  smoother 上游的 `/cmd_vel_nav`。

### 最终速度死区处理

- 实测 DWB 即使加载 `min_speed_xy=0.50`，`/cmd_vel_nav` 仍会输出合速度
  0.271~0.453 m/s；该参数是轨迹约束，不是最终速度钳位；
- 新增 `cmd_vel_speed_limiter.py`，将 Nav2 输出改到 `/cmd_vel_raw`，保持平移
  方向并把任意非零合速度归一化为 0.50 m/s，再独占发布 `/cmd_vel`；
- 零平移指令保持为零，因此取消目标、到达目标和 Nav2 超时仍可停车；
- 实机需重新启动 `navigation.launch.py` 后发送 0.3~0.5 m 短目标，确认
  `/cmd_vel` 非零样本模长为 0.50 m/s，并检查到点停车无往复振荡。
- 首次 launch 级全局 remap 验证发现 smoother 仍直接发布 `/cmd_vel`，形成两个
  发布者；已改为包内维护的 Nav2 navigation launch，逐节点明确重映射，最终
  `/cmd_vel` 必须只有 `cmd_vel_speed_limiter` 一个发布者。
- 第二轮实测确认合速度归一化为 0.50 m/s 时，最终分量仍只有 X=0.293、Y=0.405，
  不符合“每个非零 X/Y 分量至少 0.50”的底盘需求；整形逻辑改为逐轴处理，输入
  X=0.231、Y=0.320 时输出 X=0.500、Y=0.500，零分量仍保持为零。
- 第三轮实车验收采集 164 个 `/cmd_vel` 非零样本，X/Y 非零分量全部为 `±0.50`，
  单轴命令为 `(0, 0.5)`，双轴命令为 `(±0.5, 0.5)`，不再出现 0.2~0.3；
- 同期 Point-LIO `/odometry` 平移速度平均约 0.39 m/s，多次达到 0.5~0.69 m/s，
  确认 C 板已经执行提高后的速度。仍需后续处理 controller 10 Hz 偶发超时和
  `Failed to make progress`，该问题与速度指令下限无关。

### 实时代价地图障碍层修复

- `/scan` 约 10 Hz，360 束中实测 76 个有效点，范围 0.61~5.77 m，扫描时刻的
  `odom -> livox_frame` TF 可用；
- 修复前 local costmap 的 90,000 个栅格全部为 free。根因是 source 级
  `obstacle_layer.scan.max_obstacle_height` 运行值为 0，而扫描端点变换后的高度
  约为 0.287 m，所有点都被高度过滤；
- local/global costmap 的 scan source 均显式设置
  `min_obstacle_height=-0.20`、`max_obstacle_height=2.00`；
- DEBUG 验证 observation buffer 已创建但扫描未进入障碍更新；去除强制
  `sensor_frame=livox_frame`，改用 LaserScan header frame，并将 obstacle layer 的
  `tf_filter_tolerance` 设为 0，避免 MessageFilter 额外等待未来 0.05 s TF；
- LaserScan 路径调整后仍无障碍栅格，最终改用 loam_interface 已发布、frame 为
  `odom` 的 `/registered_scan` PointCloud2。该话题约 10 Hz、每帧约 260 点，可绕过
  `livox_frame` LaserScan MessageFilter，资源开销很低；
- 排查发现同时残留两套同名 Nav2（两个 controller/costmap），导致参数查询和 RViz
  数据落到不同节点；已全部停止后只启动一套，ROS 图不再报告 duplicate node；
- 单实例复验中 `/registered_scan` 同时被 local/global costmap 订阅，local costmap
  实测约 1,027 个 lethal 栅格、16,394 个 inflated 栅格，实时障碍层通过软件验收。
  仍需现场放置/移除临时障碍，确认 RViz 标记、清除、停车和重规划行为。
- 重启 Nav2 后需确认 local costmap 出现 lethal 与 inflated 栅格，并在 RViz 中
  验证临时障碍进入/移出时能够实时标记和清除。

## 2026-07-05：PID Pursuit 平移控制器部署

- 部署北极熊 `pb_omni_pid_pursuit_controller` 固定提交
  `0b95c800e61f8abbdddfcf6b07f8838b842724c3`，包版本 1.0.3；
- 在 RK3588/ROS 2 Humble 以 Release 模式完成编译，pluginlib 描述和共享库安装成功；
- 默认 FollowPath 从 DWB 切换为
  `pb_omni_pid_pursuit_controller::OmniPidPursuitController`，原配置保存为
  `nav2_params_dwb_backup.yaml`；
- 首轮 `enable_rotation=false`，平移 PID 为 Kp=1.20、Ki=0、Kd=0.05，固定前视
  0.60 m，最大合速度 0.80 m/s，目标前 0.30 m 开始减速；
- 退役逐轴 `±0.50 m/s` 硬钳位节点，恢复 PID Pursuit -> velocity smoother ->
  `/cmd_vel`；smoother 使用方向保持缩放，加速度 1.20 m/s^2、减速度 1.80 m/s^2；
- 旋转 PID 参数已预留但暂不启用。后续需先让 C 板自动模式使用
  `trans_fdb.angular_z`，并完成 rad/s 到 degree/s 及旋转方向验证；
- 尚需实车验收前进、横移、斜向、到点停车、取消目标、静态障碍停车和重规划。

### 已完成软件验收

- `pb_omni_pid_pursuit_controller` Release 构建成功，共享库和 pluginlib 索引已安装；
- controller_server 成功创建并激活 `OmniPidPursuitController`，实际运行参数确认
  `enable_rotation=false`、Kp=1.20、lookahead=0.60 m、最大线速度=0.80 m/s；
- controller_server、velocity_smoother 均为 active，PID Pursuit 启动日志无
  pluginlib/TF/costmap 错误，也没有空闲状态控制周期超时；
- 旧 `cmd_vel_speed_limiter` 节点和安装脚本已移除；`/cmd_vel_nav` 为 controller
  到 velocity_smoother 的单链；
- 实时代价地图保持正常，复验约 1,035 个 lethal、15,691 个 inflated 栅格；
- 单实例 Nav2 验证通过，未发现 duplicate node；当前尚未远程发送任何实车目标。
