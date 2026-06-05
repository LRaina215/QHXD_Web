# DO_PHASE6.md

# Phase 6：RT-Thread / C板导航通信桥接阶段

## 1. 阶段定位

当前 RK3588 已经完成：

- MID-360 接入 ROS2；
- `/livox/lidar` 点云输出；
- `PointCloud2 -> LaserScan` 转换；
- `/scan` 约 10Hz 输出；
- `slam_toolbox` 能订阅 `/scan`；
- `map_server` 能加载已保存地图；
- Nav2 相关节点可以进入初步启动测试。

当前导航链路的主要阻塞点已经从“激光雷达和建图软件能否跑起来”转移为：

- 缺少真实 `/odom`；
- 缺少 `odom -> base_link` 动态 TF；
- 缺少 Nav2 `/cmd_vel` 到 C 板 / RT-Thread 的速度下发链路；
- 缺少上位机与下位机之间面向导航任务的可靠通信协议。

因此 Phase 6 的目标不是继续调 Nav2，也不是继续扩展语音、YOLO、Dashboard，而是先完成导航闭环的底层通信基础：

```text
C板 / RT-Thread 底盘状态
    -> RK3588 ROS2 bridge
    -> /odom + /imu/data + TF

Nav2 /cmd_vel
    -> RK3588 ROS2 bridge
    -> C板 / RT-Thread
    -> 底盘执行
```

本阶段完成后，才继续回到 `slam_toolbox / AMCL / Nav2` 的真实导航测试。

---

## 2. 本阶段总目标

Phase 6 总目标：

> 基于现有可用的上下位机通信代码，改造出一套适用于 ROS2 导航的 RK3588 上位机通信节点，实现 C 板状态上发到 `/odom`、`/imu/data` 和 TF，同时实现 Nav2 `/cmd_vel` 到 C 板的安全下发。

完成后应具备：

1. RK3588 能稳定接收 C 板底盘里程计 / IMU / 状态数据；
2. RK3588 能发布 ROS2 标准 `/odom`；
3. RK3588 能广播 `odom -> base_link` 动态 TF；
4. RK3588 能发布 `/imu/data` 或 `/imu/data_raw`；
5. RK3588 能订阅 `/cmd_vel` 并转发给 C 板；
6. C 板失联或 `/cmd_vel` 超时后，底盘能自动停车；
7. 后续 `slam_toolbox / AMCL / Nav2` 能使用这套标准接口继续调试。

---

## 3. 阶段边界

### 3.1 本阶段要做

- 梳理现有上下位机通信代码；
- 设计导航用通信协议；
- 实现 ROS2 上位机 bridge 节点；
- 接收 C 板状态并发布 `/odom`；
- 接收 C 板 IMU 并发布 `/imu/data`；
- 广播 `odom -> base_link`；
- 订阅 `/cmd_vel` 并下发到底盘；
- 加入心跳、超时停车和限幅保护；
- 编写测试脚本和文档。

### 3.2 本阶段不做

- 不做完整 Nav2 到点导航验收；
- 不做 AMCL 参数精调；
- 不做 slam_toolbox 地图质量优化；
- 不做路径规划算法修改；
- 不做 YOLO 结果参与控制；
- 不做语音任务与导航目标点的最终联调；
- 不做上位机 Dashboard 大改；
- 不重构 C 板底盘控制算法；
- 不改变 RT-Thread 已有 PID / 安全闭环逻辑。

---

## 4. 推荐软件包与节点命名

建议在 RK3588 / ROS2 工作空间中新建独立包：

```text
rtt_nav_bridge
```

建议节点：

```text
rtt_nav_bridge_node
```

该节点职责：

```text
串口 / USB CDC / CAN
    <-> rtt_nav_bridge_node
    <-> ROS2 标准 topic / TF
```

建议 ROS2 topic：

```text
订阅：
- /cmd_vel                 geometry_msgs/msg/Twist

发布：
- /odom                    nav_msgs/msg/Odometry
- /imu/data 或 /imu/data_raw sensor_msgs/msg/Imu
- /rtt/status              自定义或 diagnostic_msgs/msg/DiagnosticArray
- /rtt/raw_rx              可选，调试用
- /rtt/raw_tx              可选，调试用

TF：
- odom -> base_link        动态 TF
```

---

## 5. 通信数据设计建议

实际字段需要根据你后续提供的上位机和下位机代码确定。当前先定义推荐目标格式。

### 5.1 C板 -> RK3588：ODOM 帧

推荐 C 板上发：

```text
ODOM,timestamp_ms,x,y,yaw,vx,vy,wz
```

字段说明：

| 字段 | 含义 | 单位 |
|---|---|---|
| `timestamp_ms` | C 板时间戳 | ms |
| `x` | 机器人在 odom 坐标系下的 x | m |
| `y` | 机器人在 odom 坐标系下的 y | m |
| `yaw` | 航向角 | rad |
| `vx` | 车体 x 方向速度 | m/s |
| `vy` | 车体 y 方向速度，全向底盘需要 | m/s |
| `wz` | z 轴角速度 | rad/s |

如果 C 板暂时不能给 `x/y/yaw`，最低要求也要给：

```text
ODOM,timestamp_ms,vx,vy,wz
```

此时 RK3588 侧需要临时积分出 `x/y/yaw`，但这只是第一版方案，长期更推荐 C 板直接输出融合后的里程计。

---

### 5.2 C板 -> RK3588：IMU 帧

推荐 C 板上发：

```text
IMU,timestamp_ms,qw,qx,qy,qz,gx,gy,gz,ax,ay,az
```

字段说明：

| 字段 | 含义 | 单位 |
|---|---|---|
| `qw/qx/qy/qz` | 姿态四元数 | unit quaternion |
| `gx/gy/gz` | 角速度 | rad/s |
| `ax/ay/az` | 线加速度 | m/s^2 |

若 C 板当前只能输出欧拉角：

```text
IMU,timestamp_ms,roll,pitch,yaw,gx,gy,gz,ax,ay,az
```

RK3588 bridge 需要转换为四元数后发布到 `/imu/data`。

---

### 5.3 C板 -> RK3588：状态帧

推荐 C 板上发：

```text
STAT,timestamp_ms,mode,battery_mv,estop,fault_code
```

字段说明：

| 字段 | 含义 |
|---|---|
| `mode` | C 板当前控制模式 |
| `battery_mv` | 电池电压，mV |
| `estop` | 急停状态，0/1 |
| `fault_code` | 故障码 |

---

### 5.4 RK3588 -> C板：速度指令帧

Nav2 输出 `/cmd_vel`，RK3588 转成 C 板协议。

推荐文本调试格式：

```text
CMD,timestamp_ms,vx,vy,wz
```

字段说明：

| 字段 | 含义 | 单位 |
|---|---|---|
| `vx` | 车体 x 方向速度 | m/s |
| `vy` | 车体 y 方向速度 | m/s |
| `wz` | z 轴角速度 | rad/s |

全向底盘必须保留 `vy`，不要写成只支持差速底盘的 `vx/wz`。

---

### 5.5 RK3588 -> C板：心跳 / 安全帧

推荐：

```text
HB,timestamp_ms
STOP,timestamp_ms,reason
```

用途：

- `HB`：证明 RK3588 上位机在线；
- `STOP`：上位机主动要求停车；
- C 板若超过指定时间未收到 `CMD` 或 `HB`，必须自动停车。

---

## 6. 坐标系约定

本阶段必须统一坐标系，否则后续 Nav2 会严重异常。

ROS2 移动机器人常用坐标系：

```text
x：前方
y：左方
z：上方
```

角速度：

```text
绕 z 轴逆时针为正
```

要求：

1. `/cmd_vel.linear.x` 对应车体前进速度；
2. `/cmd_vel.linear.y` 对应车体左移速度；
3. `/cmd_vel.angular.z` 对应逆时针旋转角速度；
4. C 板坐标系若与 ROS 坐标系不同，必须在 bridge 中转换；
5. `base_link` 是机器人车体坐标系；
6. `imu_link` 是 IMU 坐标系；
7. `livox_frame` 是雷达坐标系；
8. 后续 TF 树目标为：

```text
map -> odom -> base_link -> livox_frame
                      -> imu_link
```

---

## 7. 任务清单与验收标准

## Task 6.1：现有上下位机通信代码审阅

### 任务目标

基于后续提供的当前可用通信代码，确认其串口 / CAN / USB CDC 通信方式、数据帧格式、收发频率和错误处理方式，为 ROS2 bridge 改造做准备。

### 开发任务

1. 阅读当前上位机通信代码；
2. 阅读 C 板 / RT-Thread 下位机通信代码；
3. 梳理当前协议字段；
4. 确认当前链路是否已有：
   - 速度下发；
   - IMU 上发；
   - 里程计上发；
   - 急停状态上发；
   - 心跳机制；
   - CRC 或校验；
5. 输出一份 `docs/PHASE6_PROTOCOL_REVIEW.md`。

### 验收标准

- 能明确当前通信使用串口、USB CDC、CAN 或其他方式；
- 能明确通信波特率 / 端口名 / 帧头帧尾 / 校验方式；
- 能明确当前 C 板能上发哪些数据；
- 能明确当前 C 板能接收哪些控制命令；
- 能列出与 ROS2 导航接口之间的缺口。

---

## Task 6.2：定义导航用通信协议 v1

### 任务目标

在不大改底层控制逻辑的前提下，定义适用于 Nav2 的最小通信协议。

### 开发任务

1. 设计 `ODOM` 上发帧；
2. 设计 `IMU` 上发帧；
3. 设计 `STAT` 状态帧；
4. 设计 `CMD` 速度下发帧；
5. 设计 `HB` 心跳帧；
6. 设计 `STOP` 安全停车帧；
7. 明确字段单位、坐标系、频率和超时策略；
8. 输出 `docs/PHASE6_NAV_PROTOCOL_V1.md`。

### 验收标准

- 协议字段能覆盖 `/odom`、`/imu/data` 和 `/cmd_vel`；
- 单位全部明确；
- 坐标方向全部明确；
- 明确 C 板超时停车策略；
- 明确 RK3588 速度限幅策略；
- 协议可以被现有 C 板代码改造实现。

---

## Task 6.3：创建 ROS2 上位机桥接包

### 任务目标

创建 `rtt_nav_bridge` ROS2 包，用于承载导航通信桥接节点。

### 开发任务

1. 创建 ROS2 包：

```bash
ros2 pkg create rtt_nav_bridge --build-type ament_python --dependencies rclpy geometry_msgs nav_msgs sensor_msgs tf2_ros diagnostic_msgs
```

2. 新增节点：

```text
rtt_nav_bridge_node.py
```

3. 支持参数：

```text
port
baudrate
base_frame_id
odom_frame_id
imu_frame_id
cmd_vel_topic
odom_topic
imu_topic
cmd_timeout_ms
heartbeat_period_ms
max_vx
max_vy
max_wz
```

4. 支持 launch 文件：

```text
launch/rtt_nav_bridge.launch.py
```

5. 支持 YAML 配置：

```text
config/rtt_nav_bridge.yaml
```

### 验收标准

- `colcon build --packages-select rtt_nav_bridge` 通过；
- `ros2 run rtt_nav_bridge rtt_nav_bridge_node` 能启动；
- 无 C 板连接时，节点能输出明确错误，不崩溃；
- 参数能通过 YAML 配置加载；
- 不影响 Livox、LaserScan、slam_toolbox 已有链路。

---

## Task 6.4：实现 C板状态接收与解析

### 任务目标

让 RK3588 能稳定读取 C 板上发数据，并解析 `ODOM / IMU / STAT`。

### 开发任务

1. 打开串口 / USB CDC / CAN；
2. 读取下位机数据帧；
3. 实现帧解析；
4. 实现异常帧过滤；
5. 实现丢包 / 解析失败计数；
6. 增加调试日志；
7. 可选发布 `/rtt/raw_rx` 调试数据。

### 验收标准

- 能从真实 C 板持续接收数据；
- 能正确解析 IMU 帧；
- 能正确解析 ODOM 帧；
- 能正确解析 STAT 帧；
- 错误帧不会导致节点崩溃；
- 节点能统计最近 1 秒接收频率。

---

## Task 6.5：发布 `/imu/data`

### 任务目标

将 C 板 IMU 数据转换为 ROS2 标准 `sensor_msgs/msg/Imu`。

### 开发任务

1. 根据 C 板 IMU 帧填充 `sensor_msgs/msg/Imu`；
2. 设置：

```text
header.frame_id = imu_link
```

3. 填充：

```text
orientation
angular_velocity
linear_acceleration
```

4. 设置合理的 covariance；
5. 发布 `/imu/data` 或 `/imu/data_raw`；
6. 发布或文档说明 `base_link -> imu_link` 静态 TF。

### 验收标准

- `ros2 topic list | grep imu` 能看到 `/imu/data`；
- `ros2 topic hz /imu/data` 频率稳定，建议 50Hz 左右；
- `ros2 topic echo /imu/data --once` 有正确数据；
- 静止时角速度接近 0；
- 静止时加速度模长约 9.8 m/s²；
- 姿态方向与 ROS 坐标系一致或已在 bridge 中转换。

---

## Task 6.6：发布 `/odom` 与 `odom -> base_link`

### 任务目标

将 C 板里程计数据转换为 ROS2 标准 `nav_msgs/msg/Odometry`，并广播动态 TF。

### 开发任务

1. 根据 C 板 `ODOM` 帧填充 `nav_msgs/msg/Odometry`；
2. 设置：

```text
header.frame_id = odom
child_frame_id = base_link
```

3. 填充：

```text
pose.pose.position.x
pose.pose.position.y
pose.pose.orientation

twist.twist.linear.x
twist.twist.linear.y
twist.twist.angular.z
```

4. 广播动态 TF：

```text
odom -> base_link
```

5. 若 C 板只给速度，则 RK3588 侧临时积分 `x/y/yaw`；
6. 配置 covariance；
7. 增加里程计重置接口或启动归零策略。

### 验收标准

- `ros2 topic list | grep odom` 能看到 `/odom`；
- `ros2 topic hz /odom` 频率稳定，建议 30Hz ~ 50Hz；
- `ros2 topic echo /odom --once` 有正确数据；
- `ros2 run tf2_ros tf2_echo odom base_link` 能看到动态变换；
- 手推或遥控底盘移动时，x/y/yaw 按实际方向变化；
- 静止时 odom 不明显漂移；
- `slam_toolbox` 不再因缺少 odom TF 报错。

---

## Task 6.7：订阅 `/cmd_vel` 并下发 C 板

### 任务目标

将 Nav2 或手动发布的 `/cmd_vel` 转换成 C 板速度控制帧。

### 开发任务

1. 订阅：

```text
/cmd_vel
```

2. 解析：

```text
linear.x -> vx
linear.y -> vy
angular.z -> wz
```

3. 执行速度限幅：

```text
max_vx
max_vy
max_wz
```

4. 生成 C 板速度帧：

```text
CMD,timestamp_ms,vx,vy,wz
```

5. 下发到 C 板；
6. 记录下发频率；
7. 可选发布 `/rtt/raw_tx` 调试数据。

### 验收标准

- 手动发布 `/cmd_vel` 后，C 板能收到速度命令；
- `linear.x` 能控制前后运动；
- `linear.y` 能控制全向左右平移；
- `angular.z` 能控制旋转；
- 超过限幅的速度会被裁剪；
- 停止发布 `/cmd_vel` 后，底盘能在超时时间内停车。

---

## Task 6.8：安全策略与超时停车

### 任务目标

保证导航调试过程中不会因通信异常导致底盘失控。

### 开发任务

1. RK3588 侧：
   - `/cmd_vel` 超时后主动下发 0 速度；
   - 串口断开后停止发送非零速度；
   - 解析异常时不更新 odom；
   - C 板急停状态上报后，拒绝继续转发非零 `/cmd_vel`。
2. C 板侧：
   - 超过指定时间未收到 `CMD` 或 `HB` 自动停车；
   - 收到 `STOP` 立即停车；
   - 急停优先级高于速度命令。
3. 增加诊断状态。

### 验收标准

- 停止 `/cmd_vel` 发布后，底盘自动停车；
- 拔掉通信线后，底盘自动停车；
- bridge 节点崩溃后，C 板自动停车；
- 急停触发后，非零速度命令不会继续执行；
- Dashboard 或 ROS topic 能看到 fault / estop 状态。

---

## Task 6.9：与 slam_toolbox 联调

### 任务目标

让 `slam_toolbox` 使用真实 `/odom` 和 `/scan` 进行移动建图。

### 开发任务

1. 启动 MID-360；
2. 启动 pointcloud_to_laserscan；
3. 启动 rtt_nav_bridge；
4. 启动 slam_toolbox；
5. 检查 TF：

```text
map -> odom -> base_link -> livox_frame
```

6. 缓慢移动机器人，观察地图是否生成。

### 验收标准

- `ros2 topic list | grep odom` 有 `/odom`；
- `/scan` 稳定；
- `slam_toolbox` 不再报 odom / TF 缺失；
- `/map` 持续更新；
- RViz2 中地图不会严重撕裂；
- 低速移动时机器人位姿变化方向正确。

---

## Task 6.10：与 Nav2 静态导航链路联调

### 任务目标

在真实 `/odom` 和 `/cmd_vel` 桥接完成后，重新回到 Nav2 链路测试。

### 开发任务

1. 使用已保存地图启动 `map_server`；
2. 启动 AMCL；
3. 启动 Nav2；
4. 检查 lifecycle 状态；
5. 发送简单目标点；
6. 观察 `/cmd_vel` 输出；
7. 通过 bridge 下发到底盘。

### 验收标准

- `/map` 正常；
- `/amcl_pose` 正常；
- AMCL 为 active；
- Nav2 managed nodes 为 active；
- RViz2 下发 goal 后能看到 global path；
- Nav2 输出 `/cmd_vel`；
- C 板收到速度命令；
- 机器人能按照趋势向目标点运动。

本任务只验收基础链路，不要求最终导航性能最优。

---

## 8. 推荐执行顺序

建议按以下顺序推进：

1. Task 6.1：审阅现有通信代码；
2. Task 6.2：定义导航通信协议 v1；
3. Task 6.3：创建 ROS2 bridge 包；
4. Task 6.4：实现 C 板数据接收解析；
5. Task 6.5：发布 `/imu/data`；
6. Task 6.6：发布 `/odom` 与 `odom -> base_link`；
7. Task 6.7：订阅 `/cmd_vel` 并下发 C 板；
8. Task 6.8：安全策略与超时停车；
9. Task 6.9：与 slam_toolbox 移动建图联调；
10. Task 6.10：与 Nav2 静态导航链路联调。

---

## 9. Codex 分轮 Prompt

## Round 1：代码审阅与协议整理

```text
Read the current upper-computer communication code and lower-computer RT-Thread/C-board communication code provided by the user.

Task:
Implement Phase 6 Round 1: communication code review and navigation protocol proposal.

Requirements:
1. Identify the current transport method: serial, USB CDC, CAN, or other.
2. Identify current frame format, baudrate, checksum, and command types.
3. Identify what data C-board can currently send upward.
4. Identify what commands C-board can currently receive.
5. Compare current protocol with ROS2 navigation requirements.
6. Produce docs/PHASE6_PROTOCOL_REVIEW.md.
7. Produce docs/PHASE6_NAV_PROTOCOL_V1.md.

Do not modify runtime code in this round.
Do not add Nav2 or slam_toolbox changes.
```

---

## Round 2：创建 rtt_nav_bridge 包

```text
Continue from Phase 6 Round 1.

Task:
Create a ROS2 package rtt_nav_bridge for navigation communication bridging.

Requirements:
1. Create an ament_python package named rtt_nav_bridge.
2. Add rtt_nav_bridge_node.py.
3. Add launch/rtt_nav_bridge.launch.py.
4. Add config/rtt_nav_bridge.yaml.
5. Add parameters for port, baudrate, frame IDs, topic names, timeouts, and velocity limits.
6. Node should start even if the serial/CAN device is missing, but report a clear error.
7. Do not implement full protocol parsing yet.

Validation:
- colcon build --packages-select rtt_nav_bridge passes.
- ros2 run rtt_nav_bridge rtt_nav_bridge_node starts.
- ros2 launch rtt_nav_bridge rtt_nav_bridge.launch.py starts.
```

---

## Round 3：接收 C 板数据并发布 IMU

```text
Continue from Phase 6 Round 2.

Task:
Implement C-board IMU frame parsing and publish ROS2 /imu/data.

Requirements:
1. Read C-board serial/CAN data using the existing communication style.
2. Parse IMU frames according to PHASE6_NAV_PROTOCOL_V1.md.
3. Publish sensor_msgs/msg/Imu to /imu/data.
4. Fill orientation, angular_velocity, linear_acceleration.
5. Set frame_id to imu_link by default.
6. Add covariance values.
7. Add bad-frame handling and parse error counters.

Validation:
- /imu/data exists.
- ros2 topic hz /imu/data is stable.
- ros2 topic echo /imu/data --once shows valid values.
- Bad frames do not crash the node.
```

---

## Round 4：发布 Odom 与 TF

```text
Continue from Phase 6 Round 3.

Task:
Implement C-board ODOM frame parsing and publish ROS2 /odom plus odom->base_link TF.

Requirements:
1. Parse ODOM frames from C-board.
2. Publish nav_msgs/msg/Odometry to /odom.
3. Broadcast odom -> base_link dynamic TF.
4. Support vx, vy, wz for omnidirectional chassis.
5. If x/y/yaw are not provided by C-board, add temporary integration mode.
6. Make integration mode configurable.
7. Add covariance values.

Validation:
- /odom exists.
- ros2 topic hz /odom is stable.
- tf2_echo odom base_link works.
- Moving the chassis changes x/y/yaw in the correct direction.
- slam_toolbox no longer reports missing odom/base_link TF.
```

---

## Round 5：订阅 CmdVel 并下发 C 板

```text
Continue from Phase 6 Round 4.

Task:
Implement /cmd_vel subscription and C-board velocity command sending.

Requirements:
1. Subscribe to geometry_msgs/msg/Twist on /cmd_vel.
2. Convert linear.x, linear.y, angular.z to C-board CMD frame.
3. Apply configurable velocity limits.
4. Send velocity frames using the existing transport.
5. Add command send frequency logging.
6. Add optional /rtt/raw_tx debug topic.

Validation:
- Publishing /cmd_vel sends a command to C-board.
- linear.x controls forward/backward.
- linear.y controls lateral motion.
- angular.z controls rotation.
- Velocity limits are enforced.
```

---

## Round 6：安全策略与超时停车

```text
Continue from Phase 6 Round 5.

Task:
Add safety policy, heartbeat, and timeout stop behavior.

Requirements:
1. If /cmd_vel is not updated within cmd_timeout_ms, send zero velocity.
2. If bridge loses C-board connection, stop sending non-zero commands.
3. Publish diagnostic status for connection, estop, fault_code, and command timeout.
4. Send heartbeat to C-board periodically if supported.
5. Send STOP frame on shutdown if supported.
6. Do not bypass C-board emergency stop logic.

Validation:
- Stop publishing /cmd_vel and chassis stops within timeout.
- Kill bridge process and C-board stops by heartbeat timeout.
- Trigger estop and bridge refuses non-zero command.
- Diagnostic topic shows connection and fault state.
```

---

## Round 7：slam_toolbox 联调

```text
Continue from Phase 6 Round 6.

Task:
Integrate rtt_nav_bridge with current MID-360 /scan and slam_toolbox setup.

Requirements:
1. Document launch order for MID-360, pointcloud_to_laserscan, rtt_nav_bridge, and slam_toolbox.
2. Verify TF tree map->odom->base_link->livox_frame.
3. Verify /odom, /scan, and /map.
4. Add a helper script or launch file if appropriate.
5. Do not tune Nav2 yet.

Validation:
- /odom is available.
- /scan is available.
- slam_toolbox can build map while chassis moves slowly.
- RViz2 shows a reasonable map without severe tearing.
```

---

## Round 8：Nav2 基础联调

```text
Continue from Phase 6 Round 7.

Task:
Perform basic Nav2 integration after real odom and cmd_vel bridge are available.

Requirements:
1. Start map_server with saved map.
2. Start AMCL.
3. Start Nav2 bringup.
4. Verify lifecycle states.
5. Verify /cmd_vel output from Nav2.
6. Verify rtt_nav_bridge forwards /cmd_vel to C-board.
7. Keep parameters conservative for safety.

Validation:
- map_server is active.
- amcl is active.
- Nav2 managed nodes are active.
- RViz2 goal produces global path.
- Nav2 publishes /cmd_vel.
- C-board receives commands.
- Chassis moves in the expected direction under low speed limits.
```

---

## 10. 总体验收标准

Phase 6 完成后，必须满足：

1. RK3588 能从 C 板接收 IMU 数据并发布 `/imu/data`；
2. RK3588 能从 C 板接收底盘里程计并发布 `/odom`；
3. RK3588 能广播 `odom -> base_link` 动态 TF；
4. `map -> odom -> base_link -> livox_frame` TF 树完整；
5. Nav2 或手动发布的 `/cmd_vel` 能被 RK3588 转发给 C 板；
6. `/cmd_vel.linear.x / linear.y / angular.z` 与全向底盘运动方向一致；
7. `/cmd_vel` 超时、通信断开、bridge 崩溃时底盘能停车；
8. slam_toolbox 能在真实 odom 下进行移动建图；
9. map_server 和 AMCL 能使用保存地图进入定位链路；
10. Nav2 能输出 `/cmd_vel` 并通过 bridge 驱动底盘低速运动。

---

## 11. 人工验收建议

### 11.1 IMU 验收

1. 静止放置机器人；
2. 检查 `/imu/data` 频率；
3. 检查角速度接近 0；
4. 检查加速度模长约 9.8；
5. 手动旋转机器人，观察 yaw 或四元数变化方向。

### 11.2 Odom 验收

1. 原地静止 30 秒，检查 `/odom` 是否明显漂移；
2. 手动前进一小段，检查 x 是否增加；
3. 手动左移一小段，检查 y 是否增加；
4. 原地逆时针旋转，检查 yaw 是否增加；
5. 检查 `tf2_echo odom base_link` 是否连续变化。

### 11.3 CmdVel 验收

手动发布：

```bash
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
```

检查前进。

```bash
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0, y: 0.1, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
```

检查左移。

```bash
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.2}}"
```

检查逆时针旋转。

停止发布后，检查底盘是否超时停车。

---

## 12. 本阶段通过后的下一步

Phase 6 通过后，再回到导航主链路：

1. 使用真实 `/odom` 重新跑 slam_toolbox 移动建图；
2. 保存更可靠的地图；
3. 使用 `map_server + AMCL + Nav2` 做已知地图导航；
4. 调整 footprint、costmap、inflation、controller 参数；
5. 接入现有 RK3588 mission_gateway；
6. 实现语音 / Dashboard 下发目标点到 Nav2 NavigateToPose。
