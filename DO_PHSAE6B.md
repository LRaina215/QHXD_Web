# DO_PHSAE6B.md

# Phase 6B：RK3588 本地二维导航闭环验证

> 说明：文件名按用户要求保留为 `DO_PHSAE6B.md`。本阶段基于当前已完成的通信构建继续推进，重点验证 `/odom`、`/cmd_vel`、`slam_toolbox`、AMCL 与 Nav2 的最小闭环。

---

## 1. 阶段定位

当前系统已经完成：

- MID-360 通过 `livox_ros_driver2` 接入 ROS2；
- `/livox/lidar` 已可输出点云；
- `pointcloud_to_laserscan` 已将 MID-360 点云转换为 `/scan`；
- `/scan` 频率约 10Hz；
- `slam_toolbox` 已能启动并订阅 `/scan`；
- `/map_metadata` 已有有效输出；
- `map_server` 已能加载测试地图；
- 上下位机通信链路已基本打通；
- C 板已具备 odom 上发与导航速度接收基础。

Phase 6B 的目标不是继续验证单个传感器，而是进入 **RK3588 本地二维导航闭环验证**。

核心链路如下：

```text
MID-360 /scan
    +
C 板 /odom
    +
TF: odom -> base_link -> livox_frame
    ↓
slam_toolbox 建图
    ↓
map_server + AMCL 定位
    ↓
Nav2 规划与控制
    ↓
/cmd_vel
    ↓
RK3588 通信桥
    ↓
C 板 / RT-Thread 底盘执行
```

---

## 2. 本阶段总目标

完成从“通信能收发”到“导航能闭环”的验证。

阶段完成后应证明：

1. C 板上发的里程计可以被 RK3588 转换成标准 ROS2 `/odom`；
2. RK3588 能持续广播 `odom -> base_link` 动态 TF；
3. Nav2 或手动 `/cmd_vel` 能通过 RK3588 通信桥安全下发到底盘；
4. `slam_toolbox` 能基于 `/scan + /odom + TF` 进行真实移动建图；
5. 保存后的地图可以被 `map_server + AMCL` 加载并用于定位；
6. Nav2 能完成低速、短距离、可急停的目标点导航测试；
7. 后续可将导航后端接回现有 `mission_gateway`、Dashboard 和语音任务入口。

---

## 3. 本阶段不做的事情

本阶段暂不做：

- 高速导航；
- 长距离复杂路线导航；
- 多点自动巡检；
- YOLO 与 Nav2 costmap 联动；
- 复杂动态避障策略优化；
- 浏览器端完整导航地图可视化；
- OpenClaw / LLM 决策；
- systemd 服务化；
- 最终比赛级参数调优。

本阶段只追求：**低速、短距离、可控、可复现的最小二维导航闭环。**

---

## 4. 前置条件

进入 Phase 6B 前，应满足：

```text
[已完成] /livox/lidar topic 存在
[已完成] /scan topic 存在
[已完成] /scan 类型为 sensor_msgs/msg/LaserScan
[已完成] /scan 频率约 5~10Hz
[已完成] slam_toolbox 能启动
[已完成] map_server 能加载测试地图
[已完成] 上下位机通信链路能收发数据
[已完成] C 板具备 odom 上发与导航速度接收基础
```

---

# 5. 任务清单与验收标准

---

## Task 6B.1：`/odom` 标准化验证

### 任务目标

确认 C 板上发的底盘里程计数据能在 RK3588 上转换为 ROS2 标准 `/odom`。

### 输入

C 板通过串口 / USB CDC / CAN 上发里程计数据，推荐格式：

```text
ODOM,timestamp_ms,x,y,yaw,vx,vy,wz
```

如果 C 板暂时只上发速度，也可以先使用：

```text
ODOM,timestamp_ms,vx,vy,wz
```

由 RK3588 侧进行积分得到 `x, y, yaw`。

### 输出

RK3588 发布：

```text
/odom
```

消息类型：

```text
nav_msgs/msg/Odometry
```

关键字段：

```text
header.frame_id = odom
child_frame_id = base_link
pose.pose.position.x
pose.pose.position.y
pose.pose.orientation

 twist.twist.linear.x
 twist.twist.linear.y
 twist.twist.angular.z
```

### 检查命令

```bash
ros2 topic list | grep odom
ros2 topic info /odom
ros2 topic hz /odom
ros2 topic echo /odom --once
```

### 验收标准

```text
/odom 存在
/odom 类型为 nav_msgs/msg/Odometry
/odom 频率稳定，建议 >= 20Hz
header.frame_id 为 odom
child_frame_id 为 base_link
静止时 x/y/yaw 不明显漂移
前进时 x 方向变化合理
横移时 y 方向变化合理
旋转时 yaw 方向变化合理
速度单位为 m/s 和 rad/s
```

---

## Task 6B.2：`odom -> base_link` 动态 TF 验证

### 任务目标

确认 RK3588 在发布 `/odom` 的同时，持续广播：

```text
odom -> base_link
```

这是 `slam_toolbox`、AMCL 和 Nav2 正常工作的核心 TF。

### 检查命令

```bash
ros2 run tf2_ros tf2_echo odom base_link
ros2 run tf2_tools view_frames
```

### 理想 TF 树

```text
map
 ↓
odom
 ↓
base_link
 ↓
livox_frame
```

### 验收标准

```text
odom -> base_link 能持续输出
TF 时间戳持续更新
base_link 位姿变化与 /odom 一致
view_frames 中能看到 odom、base_link、livox_frame
没有大量 transform timeout / extrapolation 报错
```

### 注意事项

`odom -> base_link` 不能用静态 TF 代替。静态 TF 只能用于静止软件链路验证，不能用于真实移动建图或导航。

---

## Task 6B.3：`/cmd_vel` 手动下发与底盘安全验证

### 任务目标

在接入 Nav2 前，先手动发布 `/cmd_vel`，确认 RK3588 通信桥能将速度指令安全下发给 C 板，底盘按预期执行。

### 测试命令

前进：

```bash
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist \
"{linear: {x: 0.1, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" -r 10
```

横移：

```bash
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist \
"{linear: {x: 0.0, y: 0.1, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" -r 10
```

旋转：

```bash
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist \
"{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.2}}" -r 10
```

### 建议初始限幅

```text
|linear.x| <= 0.20 m/s
|linear.y| <= 0.20 m/s
|angular.z| <= 0.40 rad/s
```

### 验收标准

```text
linear.x 能控制前后运动
linear.y 能控制左右横移
angular.z 能控制原地旋转
运动方向符合 ROS 坐标系：x 前，y 左，z 上
停止发布 /cmd_vel 后，底盘 300~500ms 内停车
速度限幅生效
通信断开后底盘自动停车
急停 / 遥控器接管优先级高于上位机 /cmd_vel
```

### 安全要求

这一关没过之前，不能让 Nav2 直接控制底盘。

---

## Task 6B.4：MID-360 `/scan` 与雷达外参复核

### 任务目标

确认 `/scan` 在 `base_link` 坐标系下可用于二维建图与导航。

### 检查命令

```bash
ros2 topic hz /scan
ros2 topic echo /scan --qos-reliability best_effort --once
ros2 run tf2_ros tf2_echo base_link livox_frame
```

### 验收标准

```text
/scan 频率稳定，建议 5~10Hz
/scan ranges 中有有效距离值，不是全 inf
RViz2 中 LaserScan 轮廓基本连续
base_link -> livox_frame 静态 TF 存在
雷达坐标方向与车体实际方向一致
雷达高度裁剪参数不会引入大量地面、车体或天花板杂点
```

### 调试建议

如果地图方向反、墙体旋转、障碍位置明显错位，优先检查：

```text
base_link -> livox_frame 的 x/y/z
base_link -> livox_frame 的 yaw/pitch/roll
pointcloud_to_laserscan 的 min_height / max_height
```

---

## Task 6B.5：slam_toolbox 真实移动建图验证

### 任务目标

在 `/scan + /odom + TF` 都正常后，使用 `slam_toolbox` 进行低速移动建图。

### 启动链路

```text
livox_ros_driver2
pointcloud_to_laserscan
odom_bridge
base_link -> livox_frame 静态 TF
slam_toolbox
RViz2
```

### 检查命令

```bash
ros2 topic hz /scan
ros2 topic hz /odom
ros2 run tf2_ros tf2_echo odom base_link
ros2 topic echo /map_metadata --once
ros2 topic echo /pose --once
```

### 建议测试方式

第一轮只测试小范围：

```text
区域：3m × 3m 左右
速度：低速
动作：前进、后退、横移、小角度旋转
环境：尽量空旷、少动态障碍
```

### 验收标准

```text
slam_toolbox 正常启动
/map 持续更新
/map_metadata 有有效宽高与分辨率
机器人低速移动时地图不明显撕裂
直线墙体在地图中基本连续
原地旋转时地图不明显漂移
odom 与 scan 方向一致
保存地图前无严重重影和旋转畸变
```

---

## Task 6B.6：保存可用地图

### 任务目标

将 `slam_toolbox` 生成的地图保存为 Nav2 可加载的静态地图。

### 命令

```bash
mkdir -p ~/livox_ws/maps
ros2 run nav2_map_server map_saver_cli -f ~/livox_ws/maps/mid360_nav_map
```

### 输出文件

```text
~/livox_ws/maps/mid360_nav_map.yaml
~/livox_ws/maps/mid360_nav_map.pgm
```

### 验收标准

```text
yaml 文件存在
pgm 文件存在
yaml 中 image 路径正确
地图能在 RViz2 中加载
地图结构与真实环境基本一致
地图没有严重撕裂、重影、旋转畸变
```

---

## Task 6B.7：AMCL 定位验证

### 任务目标

使用保存好的地图启动 `map_server + AMCL`，验证机器人在已知地图中的定位能力。

### 推荐启动方式

```bash
ros2 launch nav2_bringup localization_launch.py \
  map:=/home/robomaster/livox_ws/maps/mid360_nav_map.yaml \
  use_sim_time:=false
```

### 检查命令

```bash
ros2 lifecycle get /map_server
ros2 lifecycle get /amcl
ros2 topic echo /amcl_pose --once
ros2 topic hz /amcl_pose
```

### 验收标准

```text
/map_server 为 active
/amcl 为 active
/amcl_pose 有输出
RViz2 中设置初始位姿后，机器人位姿能贴合地图
机器人小范围移动时，AMCL 位姿能跟随更新
没有频繁跳变、反向漂移或长时间丢定位
```

### 常见问题定位

AMCL 不稳定时，优先检查：

```text
/odom 方向和单位
odom -> base_link TF
base_link -> livox_frame 外参
/scan 高度裁剪
地图质量
AMCL 初始位姿
```

---

## Task 6B.8：Nav2 低速短距离导航验证

### 任务目标

验证 Nav2 能基于地图、AMCL、`/scan`、`/odom` 输出 `/cmd_vel`，并驱动底盘低速趋近目标点。

### 测试原则

```text
目标距离：0.5m ~ 1.0m
速度：低速
场地：空旷
人员：必须随时急停
```

### 检查命令

```bash
ros2 node list
ros2 topic list | grep cmd_vel
ros2 topic echo /cmd_vel --once
ros2 lifecycle get /controller_server
ros2 lifecycle get /planner_server
ros2 lifecycle get /bt_navigator
```

### 验收标准

```text
Nav2 managed nodes 为 active
RViz2 能发送 2D Goal Pose
Nav2 能生成 global path
local costmap 能显示障碍
/cmd_vel 有输出
底盘能按 /cmd_vel 运动
机器人能明显趋近目标点
到达目标后速度归零
异常时能取消任务或急停
```

### 注意事项

第一轮只验最小闭环，不追求路径最优、速度快或复杂避障。

---

## Task 6B.9：接回 RK3588 mission_gateway

### 任务目标

当 RViz2 发送目标点可以完成低速导航后，将导航后端接回现有任务系统。

目标链路：

```text
Dashboard / 语音
    ↓
RK3588 mission API
    ↓
mission_gateway
    ↓
local_nav_adapter
    ↓
Nav2 NavigateToPose
    ↓
/cmd_vel
    ↓
C 板 / RT-Thread
```

### 开发任务

1. 新增或完善 `local_nav_adapter`；
2. 支持 `go_to_waypoint` 转换为 Nav2 `NavigateToPose` action；
3. 支持 cancel / pause / resume 的最小实现；
4. 将 Nav2 状态回写到 RK3588 `state_store`；
5. 保留 `MISSION_BACKEND=nuc` 作为 fallback；
6. 新增 `MISSION_BACKEND=local_nav`；
7. 不改变前端和语音接口。

### 验收标准

```text
/api/mission/go_to_waypoint 能调用 Nav2 goal
语音“去一号点”能解析为 waypoint
waypoint 能映射为 map 坐标
Dashboard 能显示 navigating / reached / failed
取消任务时 Nav2 goal 能取消
MISSION_BACKEND=nuc 仍可回退
MISSION_BACKEND=local_nav 能走本地导航
```

---

# 6. 阶段总体验收标准

Phase 6B 完成后应满足：

```text
[ ] /odom 存在且频率稳定
[ ] odom -> base_link 动态 TF 正常
[ ] /cmd_vel 能安全下发到底盘
[ ] 通信断开或停止发布后底盘能自动停车
[ ] /scan 在 base_link 坐标系下可用
[ ] slam_toolbox 能完成小范围真实移动建图
[ ] 地图能保存为 yaml + pgm
[ ] map_server 能加载保存地图
[ ] AMCL 能在地图中定位
[ ] Nav2 能输出 /cmd_vel
[ ] 机器人能完成低速短距离 goal 测试
[ ] mission_gateway 能切换到 local_nav 后端
```

---

# 7. 推荐执行顺序

严格按照以下顺序推进：

```text
1. 验证 /odom
2. 验证 odom -> base_link TF
3. 手动验证 /cmd_vel 下发
4. 复核 /scan 与雷达外参
5. slam_toolbox 移动建图
6. 保存地图
7. AMCL 定位
8. Nav2 低速短距离导航
9. 接回 mission_gateway / Dashboard / 语音
```

不要跳过 `/odom` 和 `/cmd_vel` 直接跑 Nav2。

---

# 8. 人工测试记录表

建议每次测试记录以下内容：

```text
测试日期：
测试人员：
系统平台：RK3588 / NUC
ROS2 版本：Humble
雷达：MID-360
地图文件：

/scan 频率：
/odom 频率：
cmd_vel 限幅：
是否可急停：
地图是否撕裂：
AMCL 是否稳定：
Nav2 是否输出 cmd_vel：
机器人是否到达目标：
主要问题：
下一步修改：
```

---

# 9. 当前阶段结论

现在通信已经基本打通，下一步就是导航闭环验证。核心不是继续堆新功能，而是按顺序打通：

```text
/odom
→ /cmd_vel
→ 移动建图
→ AMCL
→ Nav2
→ mission_gateway
```

只有完成这些，RK3588 本地二维导航才能从“软件栈能启动”进入“机器人能实际自主移动”的阶段。
